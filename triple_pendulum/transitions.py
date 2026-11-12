"""Certified directed equilibrium-to-equilibrium transitions for orders 1–5."""
from pathlib import Path
from itertools import product
from copy import deepcopy
import hashlib,json,time,uuid,os
import numpy as np
from .model import Plant,Parameters,wrap
from . import repository

ROOT=Path(__file__).resolve().parent.parent/'equilibrium_transitions'
RATE=500.
MAX_ORDER=5
CLUSTER_MODE=os.environ.get('PENDULUM_CLUSTER_MODE')=='1'
_initialized_root=None

def patterns(n):
    if n not in range(1,MAX_ORDER+1):raise ValueError('稳态互转仅开放 1～5 阶')
    return [''.join(p) for p in product('UD',repeat=n)]

def equilibrium(plant,code):
    if code not in patterns(plant.n):raise ValueError('无效稳态')
    x=np.zeros(plant.dim);x[1:plant.d]=repository.angles(code);return x

def key(n,source,target):return f'{n}-{source}-{target}'

def initialize():
    global _initialized_root
    ROOT.mkdir(exist_ok=True)
    if CLUSTER_MODE:
        for directory in ('certificates','progress','rejections'):(ROOT/directory).mkdir(exist_ok=True)
        _initialized_root=ROOT;return
    path=ROOT/'status.json'
    if _initialized_root==ROOT and path.exists():return
    if path.exists() and json.loads(path.read_text(encoding='utf8')).get('max_order',0)>=MAX_ORDER:
        _initialized_root=ROOT;return
    with repository.disk_lock():
        rows=json.loads(path.read_text(encoding='utf8'))['entries'] if path.exists() else {}
        for n in range(1,MAX_ORDER+1):
            for a in patterns(n):
                for b in patterns(n):
                    if a!=b:rows.setdefault(key(n,a,b),dict(order=n,source=a,target=b,status='queued'))
        _write(rows)
    _initialized_root=ROOT

def _write(rows):
    temp=ROOT/('status-'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(dict(schema=2,max_order=MAX_ORDER,entries=rows),ensure_ascii=False,indent=2),encoding='utf8')
    for i in range(30):
        try:temp.replace(ROOT/'status.json');return
        except PermissionError:
            if i==29:raise
            time.sleep(.02)

def statuses():
    initialize()
    for i in range(30):
        try:
            rows=json.loads((ROOT/'status.json').read_text(encoding='utf8'))['entries']
            if CLUSTER_MODE:
                for path in (ROOT/'progress').glob('*.json'):
                    try:
                        value=json.loads(path.read_text(encoding='utf8'));k=key(value['order'],value['source'],value['target'])
                        if rows[k]['status']!='ready':rows[k].update(value)
                    except (OSError,ValueError,KeyError):continue
                for path in (ROOT/'certificates').glob('*.json'):
                    try:
                        value=json.loads(path.read_text(encoding='utf8'));k=key(value['order'],value['source'],value['target']);rejection=ROOT/'rejections'/(k+'.json')
                        rejected=json.loads(rejection.read_text()) if rejection.exists() else {}
                        if rejected.get('sha256')==value['sha256']:
                            rows[k].update(status='retry_pending',phase='本机复验未通过，重新搜索');continue
                        rows[k]=value
                    except (OSError,ValueError,KeyError):continue
            return rows
        except PermissionError:
            if i==29:raise
            time.sleep(.02)

def update(n,source,target,**values):
    initialize()
    if CLUSTER_MODE:
        k=key(n,source,target);certificate=ROOT/'certificates'/(k+'.json');rejection=ROOT/'rejections'/(k+'.json')
        if certificate.exists():
            data=json.loads(certificate.read_text());rejected=json.loads(rejection.read_text()) if rejection.exists() else {}
            if data['sha256']!=rejected.get('sha256'):return
        path=ROOT/'progress'/(k+'.json')
        data=json.loads(path.read_text()) if path.exists() else dict(order=n,source=source,target=target,status='computing')
        data.update(values,updated_at=time.time());temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8');temporary.replace(path)
        return
    with repository.disk_lock():
        rows=statuses();row=rows[key(n,source,target)]
        if row['status']=='ready' and values.get('status')!='ready':return
        row.update(values,updated_at=time.time());_write(rows)

def catalog(n=None):
    all_rows=list(statuses().values());rows=[r for r in all_rows if n is None or r['order']==n]
    audit_path=ROOT.parent/'results/fourth-order-worker-audit.json'
    try:audit=json.loads(audit_path.read_text(encoding='utf8'))
    except (OSError,ValueError):audit={}
    signature=bank_signature(all_rows)
    if not(audit.get('passed') and audit.get('bank_sha256')==signature):
        try:audit=json.loads((audit_path.parent/'fourth-order-worker-audits'/(signature+'.json')).read_text(encoding='utf8'))
        except (OSError,ValueError):audit={}
    cruise={order:sum(r['status']=='ready' for r in all_rows if r['order']==order)==2**order*(2**order-1) for order in range(1,MAX_ORDER+1)}
    cruise[4]=cruise[4] and audit.get('passed',False) and audit.get('bank_sha256')==signature
    fifth_signature=bank_signature(all_rows,order=5)
    try:fifth_audit=json.loads((audit_path.parent/'fifth-order-worker-audit.json').read_text(encoding='utf8'))
    except (OSError,ValueError):fifth_audit={}
    cruise[5]=cruise[5] and fifth_audit.get('passed',False) and fifth_audit.get('bank_sha256')==fifth_signature
    remote_path=ROOT.parent/'results/fourth-order-remote.json'
    try:remote=json.loads(remote_path.read_text(encoding='utf8'))
    except (OSError,ValueError):remote=None
    try:fifth_remote=json.loads((remote_path.parent/'fifth-order-remote.json').read_text(encoding='utf8'))
    except (OSError,ValueError):fifth_remote=None
    return dict(total=len(rows),ready=sum(r['status']=='ready' for r in rows),entries=rows,force_rate=RATE,cruise_ready=cruise,remote_compute=fifth_remote if n==5 else remote,remote_computes={4:remote,5:fifth_remote})

def bank_signature(rows=None,order=4):
    if rows is None:rows=list(statuses().values())
    fingerprints=[key(order,r['source'],r['target'])+':'+r.get('sha256','') for r in rows if r['order']==order]
    return hashlib.sha256('\n'.join(sorted(fingerprints)).encode()).hexdigest()

def admit(plant,source,target,plan,report,history):
    if source==target:raise ValueError('自稳不计入转场')
    np.testing.assert_allclose(plan['initial'],equilibrium(plant,source),atol=1e-8)
    if repository.pattern(plan['target_angles'])!=target:raise ValueError('目标不匹配')
    if not(report['final_stable'] and report['max_cart']<plant.p.rail*.96 and report['max_force']<=plant.p.max_force and report['max_tracking_error']<3 and report['max_force_rate']<=RATE+1e-6):return False
    data=deepcopy(plan);data.update(success=True,pattern=target,parameters=plant.p.dict(),verification=report,force_rate=RATE,strict_rest=True,
        transition=dict(order=plant.n,source=source,target=target),wall_seconds=0.,source='离线稳态互转 · 独立物理验收')
    encoded=json.dumps(data,ensure_ascii=False).encode('utf8');name=key(plant.n,source,target)+'.json'
    if CLUSTER_MODE:
        digest=hashlib.sha256(encoded).hexdigest();name=key(plant.n,source,target)+'-'+digest[:16]+'.json'
        temporary=ROOT/(name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(encoded);temporary.replace(ROOT/name)
        row=dict(order=plant.n,source=source,target=target,status='ready',file=name,sha256=digest,parameters=plant.p.dict(),duration=data['duration'],verification=report,updated_at=time.time())
        path=ROOT/'certificates'/(key(plant.n,source,target)+'.json');temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(row,ensure_ascii=False),encoding='utf8');temporary.replace(path)
        return True
    meta=repository.store(data,plant,history,title='稳态互转 '+repository.label(source)+' → '+repository.label(target))
    with repository.disk_lock():
        rows=statuses();row=rows[key(plant.n,source,target)]
        if row['status']=='ready' and not(row.get('route_waypoints') and not data.get('route_waypoints')):return True
        temp=ROOT/(name+'.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(encoded);temp.replace(ROOT/name)
        row.update(status='ready',file=name,sha256=hashlib.sha256(encoded).hexdigest(),parameters=plant.p.dict(),duration=data['duration'],verification=report,repository_id=meta['id'],updated_at=time.time())
        if data.get('route_waypoints'):row['route_waypoints']=data['route_waypoints']
        else:row.pop('route_waypoints',None)
        _write(rows)
    return True

def lookup(plant,source,target):
    if source not in patterns(plant.n) or target not in patterns(plant.n) or source==target:raise ValueError('请选择不同的起止稳态')
    row=statuses()[key(plant.n,source,target)]
    if row['status']!='ready' or row.get('parameters')!=plant.p.dict():return None
    encoded=(ROOT/row['file']).read_bytes()
    if hashlib.sha256(encoded).hexdigest()!=row['sha256']:raise ValueError('转场文件校验失败')
    plan=json.loads(encoded);plan['pattern']=target
    return plan
