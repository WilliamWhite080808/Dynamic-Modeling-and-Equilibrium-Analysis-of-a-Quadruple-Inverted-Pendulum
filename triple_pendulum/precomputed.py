"""Offline-certified hanging swing-up bank. Runtime lookup never invokes a solver."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import threading
import time
import numpy as np
from .model import Plant,Parameters,wrap
from . import repository

ROOT=Path(__file__).resolve().parent.parent/'precomputed_swingups'
LOCK=threading.RLock()

def hanging(plant):
    initial=np.zeros(plant.dim);initial[1:plant.d]=np.pi
    return initial

def initialize():
    ROOT.mkdir(exist_ok=True)
    path=ROOT/'status.json'
    if not path.exists():
        rows={f'{n}-{code}':dict(order=n,pattern=code,status='queued',attempts=0) for n in range(1,6) for code in repository.patterns(n)}
        _status_write(rows)

def _status_write(rows):
    path=ROOT/'status.tmp';path.write_text(json.dumps(dict(version=1,entries=rows),ensure_ascii=False,indent=2),encoding='utf8')
    for attempt in range(10):
        try:path.replace(ROOT/'status.json');return
        except PermissionError:
            if attempt==9:raise
            time.sleep(.02)

def statuses():
    initialize()
    # Windows can briefly deny reads while another process atomically replaces
    # the progress file. A short retry keeps background publication transparent.
    for attempt in range(50):
        try:return json.loads((ROOT/'status.json').read_text(encoding='utf8'))['entries']
        except PermissionError:
            if attempt==49:raise
            time.sleep(.02)

def update(order,code,**values):
    initialize()
    with LOCK,repository.disk_lock():
        rows=statuses();row=rows[f'{order}-{code}']
        if row.get('status')=='ready' and values.get('status')!='ready':return
        row.update(values,updated_at=time.time());_status_write(rows)

def put(plant,code,plan,report,repository_id=None):
    if not report.get('final_stable') or report['max_cart']>=plant.p.rail*.96 or report['max_force']>plant.p.max_force or report.get('max_tracking_error',float('inf'))>=3:
        raise ValueError('方案没有通过悬垂起摆闭环验收')
    initial=np.asarray(plan['initial'])
    if initial.shape!=(plant.dim,) or abs(initial[0])>1e-10 or np.max(abs(wrap(initial[1:plant.d]-np.pi)))>1e-10 or np.max(abs(initial[plant.d:]))>1e-10 or plan['duration']<=0:
        raise ValueError('预优化初值必须为轨道中央完全下垂、全速度为零')
    if repository.pattern(plan.get('target_angles',[0.]*plant.n))!=code:raise ValueError('目标姿态与条目不一致')
    data=deepcopy(plan);data.update(parameters=plant.p.dict(),verification=report,success=True,precomputed=True,
        source='离线预优化 + 独立闭环验证',wall_seconds=0.,repository_id=repository_id,pattern=code)
    encoded=json.dumps(data,ensure_ascii=False).encode('utf8');digest=hashlib.sha256(encoded).hexdigest()
    name=f'{plant.n}-{code}.json'
    with LOCK,repository.disk_lock():
        rows=statuses();row=rows[f'{plant.n}-{code}']
        # Independent search methods may finish the same target together. Publish
        # file + digest under one lock and leave an admitted file immutable.
        if row.get('status')=='ready':return
        ROOT.mkdir(exist_ok=True);temp=ROOT/(name+'.tmp');temp.write_bytes(encoded);temp.replace(ROOT/name)
        row.update(status='ready',phase='独立非线性闭环验收通过',last_error=None,file=name,sha256=digest,
            parameters=plant.p.dict(),verification=report,repository_id=repository_id,updated_at=time.time(),duration=plan['duration'])
        _status_write(rows)

def lookup(plant,initial,goal):
    code=repository.pattern(goal)
    if len(code)!=plant.n or code=='D'*plant.n:return None
    s=np.asarray(initial,dtype=float)
    if s.shape!=(plant.dim,) or not np.isfinite(s).all() or abs(s[0])>1e-10 or np.max(abs(s[plant.d:]))>1e-10 or np.max(abs(wrap(s[1:plant.d]-np.pi)))>1e-10:return None
    from .motion_plugins import active
    store=active()
    if store:return store.lookup(plant,'D'*plant.n,code)
    row=statuses().get(f'{plant.n}-{code}',{})
    if row.get('status')!='ready' or row.get('parameters')!=plant.p.dict():return None
    encoded=(ROOT/row['file']).read_bytes()
    if hashlib.sha256(encoded).hexdigest()!=row['sha256']:raise ValueError('预优化文件校验失败，请离线重新生成')
    data=json.loads(encoded)
    shifts=s[1:plant.d]-np.asarray(data['initial'])[1:plant.d]
    if np.max(abs(shifts))>1e-10:
        states=np.asarray(data['states']);states[:,1:plant.d]+=shifts;data['states']=states.tolist()
    data['initial']=s.tolist()
    return data

def catalog(order=None):
    from .motion_plugins import active
    store=active()
    if store:
        rows=[dict(r,pattern=r['target']) for r in store.catalog(order)['entries'] if r['source']=='D'*r['order'] and r['target']!='D'*r['order']]
        return dict(total=len(rows),ready=sum(r['status']=='ready' for r in rows),entries=rows)
    rows=list(statuses().values())
    if order is not None:rows=[r for r in rows if r['order']==order]
    return dict(total=len(rows),ready=sum(r['status']=='ready' for r in rows),entries=rows)

def import_verified():
    from .validate_plan import replay
    initialize();count=0
    for meta in repository.catalog():
        if not meta.get('has_control_plan',True):continue
        p=Plant(Parameters(**meta['parameters']));s=np.asarray(meta['initial']);code=meta['pattern']
        if abs(s[0])>1e-10 or np.max(abs(s[p.d:]))>1e-10 or np.max(abs(wrap(s[1:p.d]-np.pi)))>1e-10:continue
        row=statuses().get(f'{p.n}-{code}')
        if not row or row['status']=='ready':continue
        data=repository.read(meta['id']);plan=data.get('control_plan')
        if not plan or plan['duration']<=0:continue
        report=replay(p,plan,total=plan['duration']+8);report.pop('history')
        if report['final_stable'] and report['max_cart']<p.p.rail*.96 and report['max_tracking_error']<3:
            put(p,code,plan,report,meta['id']);count+=1
    return count
