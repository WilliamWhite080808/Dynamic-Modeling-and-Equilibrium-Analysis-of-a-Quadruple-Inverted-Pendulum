"""Versioned motion pairs, activated only by an explicit directory scan.

The cache holds immutable copies, not references into the editable source tree.
The lossless state-Hermite representation retains the certified controller.
"""
from pathlib import Path
from copy import deepcopy
import gzip,hashlib,json,math,threading,time,uuid,os,re
import numpy as np
from .model import Parameters
from .motion_text import read_motion,loads as read_toml

ROOT=Path(__file__).resolve().parent.parent
LOCK=threading.RLock()
_store=None

def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')
def digest(value):return hashlib.sha256(encoded(value)).hexdigest()
def model_digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')).hexdigest()
def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(encoded(value));temp.replace(path)

def runtime(plan):
    return {k:plan[k] for k in ('duration','dt','initial','target_angles','states','derivatives','forces','gains')}

def pack(plan):
    n=plan['parameters']['n'];d=n+1;s=np.asarray(plan['states']);ds=np.asarray(plan['derivatives'])
    if not np.array_equal(ds[:,:d],s[:,d:]):raise ValueError('参考导数与速度不一致，不能无损压缩')
    out=dict(T=plan['duration'],h=plan['dt'],q=s[:,:d].tolist(),v=s[:,d:].tolist(),a=ds[:,d:].tolist(),u=plan['forces'],K=plan['gains'],runtime_sha256=digest(runtime(plan)),proof=plan['verification'])
    if 'worker_verification' in plan:out['worker']=plan['worker_verification']
    if 'direct_quality' in plan:out['direct']=plan['direct_quality']
    source=plan['transition']['source'];target=plan['transition']['target']
    initial=[0.,*[0. if c=='U' else math.pi for c in source],*([0.]*d)]
    goal=[0. if c=='U' else math.pi for c in target]
    if encoded(plan['initial'])!=encoded(initial):out['initial']=plan['initial']
    if encoded(plan['target_angles'])!=encoded(goal):out['target']=plan['target_angles']
    return out

def unpack(data,n,source,target,parameters):
    q=np.asarray(data['q'],dtype=float);v=np.asarray(data['v'],dtype=float);a=np.asarray(data['a'],dtype=float);u=np.asarray(data['u'],dtype=float);K=np.asarray(data['K'],dtype=float)
    d=n+1;count=len(q)
    if count<2 or count>20000 or q.shape!=(count,d) or v.shape!=q.shape or a.shape!=q.shape or u.shape!=(count,) or K.shape!=(count,2*d):raise ValueError('轨迹维度不符')
    if not all(np.isfinite(x).all() for x in (q,v,a,u,K)):raise ValueError('轨迹含非有限值')
    T=float(data['T']);h=float(data['h'])
    if not 0<T<=120 or abs(h*(count-1)-T)>1e-7:raise ValueError('轨迹时标不符')
    expected=[0.,*[0. if c=='U' else math.pi for c in source],*([0.]*d)]
    initial=data.get('initial',expected);goal=data.get('target',[0. if c=='U' else math.pi for c in target])
    if initial!=expected or len(goal)!=n or ''.join('U' if math.cos(x)>0 else 'D' for x in goal)!=target:raise ValueError('轨迹端点不符')
    plan=dict(duration=data['T'],dt=data['h'],states=np.column_stack((q,v)).tolist(),derivatives=np.column_stack((v,a)).tolist(),forces=data['u'],gains=data['K'],initial=initial,target_angles=goal)
    if digest(runtime(plan))!=data['runtime_sha256']:raise ValueError('控制参考摘要不符')
    p=data['proof'];worker=data.get('worker',{})
    if not p.get('final_stable') or p['max_cart']>=parameters['rail']*.96 or p['max_force']>parameters['max_force']+1e-6 or p['max_force_rate']>500+1e-6 or p.get('max_tracking_error',float('inf'))>=3:raise ValueError('物理验收未通过')
    if worker and (not worker.get('individual') or worker.get('rail_contacts')!=0 or worker.get('live_planner_requests')!=0):raise ValueError('Worker 验收未通过')
    if data.get('direct',{}).get('passed') is False:raise ValueError('直达验收未通过')
    plan.update(success=True,parameters=parameters,verification=p,pattern=target,transition=dict(order=n,source=source,target=target),force_rate=500.,strict_rest=True,wall_seconds=0.,source='双向轨迹插件 · 无损控制参考')
    if worker:plan['worker_verification']=worker
    if 'direct' in data:plan['direct_quality']=data['direct']
    return plan

class MotionStore:
    def __init__(self,root):
        self.root=Path(root);self.cache=self.root/'.cache/motions';self.index=self.root/'.cache/trajectory-index.json';self.lock=threading.RLock();self.plans={}
        if os.environ.get('PENDULUM_CACHE_HOME'):self.cache=Path(os.environ['PENDULUM_CACHE_HOME'])/'motions'
        if self.index.exists():
            try:json.loads(self.index.read_text(encoding='utf8'))
            except (OSError,ValueError):self.index.rename(self.index.with_name('trajectory-index.bad-'+str(time.time_ns())+'.json'))
        if not self.index.exists():self.refresh()
        self.load()

    def load(self):
        value=json.loads(self.index.read_text(encoding='utf8'))
        if value.get('v')!=1:raise ValueError('轨迹索引版本不支持')
        self.value=value;self.plans={};self.seed_errors={}
        for filename,meta in value['files'].items():
            if meta.get('seed_source'):
                try:self.restore_seed(meta)
                except (OSError,ValueError) as error:self.seed_errors[filename]=str(error)

    def restore_seed(self,meta):
        sha=meta.get('cache_sha256',meta['sha256']);target=self.cache/(sha+meta.get('ext','.json'))
        if target.exists():return
        name=meta.get('seed_source')
        if not name or Path(name).name!=name:raise ValueError('缺少可重建的预载轨迹')
        raw=(self.root/'motions'/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('预载缓存缺失且源文件已改变，请手动检查轨迹更新')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(raw);temporary.replace(target)

    def cached_document(self,meta):
        sha=meta.get('cache_sha256',meta['sha256']);ext=meta.get('ext','.json')
        path=self.cache/(sha+ext)
        if not path.exists() and meta.get('seed_source'):self.restore_seed(meta)
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('已激活缓存损坏')
        return json.loads(gzip.decompress(raw)) if ext=='.json.gz' else read_motion(raw)

    def validate(self,raw,model):
        doc=read_motion(raw);n=doc['n'];ends=doc['ends']
        if doc.get('v') not in (1,2) or doc.get('basis')!='state-hermite-v1' or not isinstance(n,int) or not 1<=n<=20 or len(ends)!=2 or ends[0]==ends[1] or any(len(x)!=n or set(x)-set('UD') for x in ends):raise ValueError('插件类别或端点无效')
        params=Parameters(n=n,**model['parameters']).dict()
        if doc.get('model_sha256') not in (digest(model),model_digest(model)):raise ValueError('插件物理模型不匹配')
        for direction,a,b in (('ab',ends[0],ends[1]),('ba',ends[1],ends[0])):unpack(doc[direction],n,a,b,params)
        return doc,params

    def certificate_only_update(self,raw,previous,old_model,new_model):
        # Sequence certificates do not change the physical reference. Accept this
        # fast path only when every byte except the model-hash line is identical.
        if not previous or previous.get('ext')!='.toml':return False
        if {k:v for k,v in old_model.items() if k!='sequence_signatures'}!={k:v for k,v in new_model.items() if k!='sequence_signatures'}:return False
        path=self.cache/(previous['cache_sha256']+'.toml')
        try:prior=path.read_bytes()
        except OSError:return False
        if hashlib.sha256(prior).hexdigest()!=previous['cache_sha256']:return False
        pattern=br'(?m)^model = "([0-9a-f]{64})"\r?\n'
        a=re.search(pattern,prior);b=re.search(pattern,raw)
        if not a or not b:return False
        if a.group(1).decode() not in (digest(old_model),model_digest(old_model)) or b.group(1).decode() not in (digest(new_model),model_digest(new_model)):return False
        return re.sub(pattern,b'model = ""\n',prior,count=1)==re.sub(pattern,b'model = ""\n',raw,count=1)

    def refresh(self):
        with self.lock:
            old=json.loads(self.index.read_text(encoding='utf8')) if self.index.exists() else {'files':{}}
            model_path=self.root/'models/standard.toml'
            model=read_toml(model_path.read_bytes()) if model_path.exists() else json.loads((self.root/'models/standard.json').read_text(encoding='utf8'));files={};errors=[]
            self.cache.mkdir(parents=True,exist_ok=True)
            paths=list((self.root/'motions').glob('*.motion.json'))+list((self.root/'motions').glob('*.toml'))
            for number,path in enumerate(sorted(paths),1):
                if number==1 or number%20==0:(self.root/'.cache/trajectory-progress.txt').write_text(f'正在校验轨迹 {number} / {len(paths)}',encoding='utf8')
                try:
                    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
                    previous=old['files'].get(path.name)
                    if previous and previous['sha256']!=sha and self.certificate_only_update(raw,previous,old.get('model',{}),model):
                        target=self.cache/(sha+'.toml');temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(raw);temporary.replace(target)
                        files[path.name]=dict(previous,sha256=sha,cache_sha256=sha,seed_source=path.name);continue
                    unchanged=previous and previous['sha256']==sha and old.get('model')==model and previous.get('directions')
                    if unchanged and previous.get('ext')=='.toml':
                        try:
                            self.restore_seed(previous)
                            snapshot=self.cache/(previous['cache_sha256']+'.toml')
                            if hashlib.sha256(snapshot.read_bytes()).hexdigest()==previous['cache_sha256']:
                                files[path.name]=previous;continue
                        except (OSError,ValueError):pass
                        unchanged=False
                    if unchanged and previous.get('ext')=='.json.gz':
                        self.cached_document(previous);files[path.name]=previous;continue
                    if unchanged:doc=self.cached_document(previous);params=previous['parameters']
                    else:doc,params=self.validate(raw,model)
                    compact=read_toml(raw).get('v') in (3,4) if not raw.lstrip().startswith(b'{') else False
                    cached=raw if compact else gzip.compress(encoded(doc),compresslevel=3,mtime=0);cache_sha=hashlib.sha256(cached).hexdigest();ext='.toml' if compact else '.json.gz';target=self.cache/(cache_sha+ext)
                    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=cache_sha:target.write_bytes(cached)
                    directions={k:{x:doc[k][x] for x in ('runtime_sha256','T','proof')} for k in ('ab','ba')}
                    files[path.name]=dict(sha256=sha,cache_sha256=cache_sha,n=doc['n'],ends=doc['ends'],parameters=params,directions=directions,ext=ext)
                    if compact:files[path.name]['seed_source']=path.name
                except Exception as error:
                    errors.append(dict(file=path.name,error=str(error)))
                    if path.name in old['files']:files[path.name]=old['files'][path.name]
            # Model mismatches must not invalidate a previously activated snapshot.
            if errors and old.get('model') and model_digest(old['model'])!=model_digest(model):
                return dict(changed=False,errors=errors,orders=sorted({x['n'] for x in old['files'].values()}),directions=2*len(old['files']))
            changed=files!=old['files']
            value=dict(v=1,activated_at=time.time(),model=model,files=files)
            if old.get('source_preload'):value['source_preload']=True
            atomic(self.index,value);self.value=value;self.plans={};self.seed_errors={}
            (self.root/'.cache/trajectory-progress.txt').write_text(f'已就绪：{len(files)} 对、{2*len(files)} 条方向',encoding='utf8')
            return dict(changed=changed,errors=errors,orders=self.orders(),directions=2*len(files),pairs=len(files))

    def orders(self):return sorted({v['n'] for k,v in self.value['files'].items() if k not in getattr(self,'seed_errors',{})})

    def lookup(self,plant,source,target):
        with self.lock:
            for filename,meta in self.value['files'].items():
                if filename in getattr(self,'seed_errors',{}):continue
                if meta['n']!=plant.n or set(meta['ends'])!={source,target} or meta['parameters']!=plant.p.dict():continue
                k=(meta['sha256'],source)
                if k not in self.plans:
                    doc=self.cached_document(meta);direction='ab' if source==doc['ends'][0] else 'ba';self.plans[k]=unpack(doc[direction],plant.n,source,target,meta['parameters'])
                return deepcopy(self.plans[k])
        return None

    def catalog(self,n=None):
        with self.lock:
            ready={}
            for filename,meta in self.value['files'].items():
                if filename in getattr(self,'seed_errors',{}):continue
                order=meta['n']
                if n is not None and n!=order:continue
                doc=meta.get('directions') or self.cached_document(meta)
                for direction,a,b in (('ab',meta['ends'][0],meta['ends'][1]),('ba',meta['ends'][1],meta['ends'][0])):
                    data=doc[direction];ready[(order,a,b)]=dict(order=order,source=a,target=b,status='ready',sha256=data['runtime_sha256'],parameters=meta['parameters'],duration=data['T'],verification=data['proof'])
            rows=[]
            for order in ([n] if n else self.orders()):
                if order not in self.orders():continue
                codes=[format(i,'0%db'%order).replace('0','U').replace('1','D') for i in range(2**order)]
                rows.extend(ready.get((order,a,b),dict(order=order,source=a,target=b,status='unavailable')) for a in codes for b in codes if a!=b)
            sequences={}
            for order in self.orders():
                fingerprints=sorted(f'{a}-{b}:{r["sha256"]}' for (n,a,b),r in ready.items() if n==order)
                signature=hashlib.sha256('\n'.join(fingerprints).encode()).hexdigest()
                sequences[order]=len(fingerprints)==2**order*(2**order-1) and self.value['model'].get('sequence_signatures',{}).get(str(order))==signature
            return dict(total=len(rows),ready=len(ready),entries=rows,orders=self.orders(),force_rate=500.,cruise_ready=sequences,remote_compute=None,remote_computes={},plugin_mode=True)

def active():
    global _store
    if not (ROOT/'motions').is_dir():return None
    with LOCK:
        if _store is None:_store=MotionStore(ROOT)
        return _store
