"""Local initial-state / target / verified-control trajectory repository."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import hashlib
import json
import threading
import time
import os,socket,uuid
from itertools import product
from contextlib import contextmanager
import numpy as np
from .model import Plant,Parameters,wrap
from .control import analyze

ROOT=Path(__file__).resolve().parent.parent/'trajectory_repository'
LOCK=threading.RLock()
PATTERNS=['UUU','UUD','UDU','UDD','DUU','DUD','DDU']

def patterns(order):
    if not 1<=order<=20:raise ValueError('无效摆杆阶数')
    return [''.join(chars) for chars in product('UD',repeat=order) if 'U' in chars]

def angles(pattern):
    if not pattern or any(c not in 'UD' for c in pattern):raise ValueError('目标姿态只接受 U/D')
    return [0. if c=='U' else float(np.pi) for c in pattern]

def pattern(goal):return ''.join('U' if np.cos(v)>0 else 'D' for v in goal)
def label(code):return ' / '.join('上' if c=='U' else '下' for c in code)

def read(ident):
    if len(ident)!=24 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('Invalid solution ID')
    return json.loads((ROOT/(ident+'.json')).read_text(encoding='utf8'))

def catalog():
    with LOCK:
        path=ROOT/'index.json'
        for attempt in range(30):
            try:return json.loads(path.read_text(encoding='utf8'))['solutions'] if path.exists() else []
            except PermissionError:
                if attempt==29:raise
                time.sleep(.02)

def store(plan,plant,history,source='独立积分验证',title=None):
    goal=plan.get('target_angles',[0.]*plant.n);code=pattern(goal);initial=np.array(plan['initial'])
    normalized=initial.copy();normalized[1:plant.d]=wrap(normalized[1:plant.d])
    fingerprint=json.dumps([plant.p.dict(),normalized.round(9).tolist(),code],sort_keys=True)
    ident=hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
    frames=[[0.,*initial.tolist(),0.]]+[[float(row[0]+.001),*row[1:].tolist()] for row in history]
    report=plan['verification']
    meta=dict(id=ident,order=plant.n,title=title or f'初值 → {label(code)}',pattern=code,target_label=label(code),
              initial=initial.tolist(),target_angles=goal,parameters=plant.p.dict(),source=source,
              duration=frames[-1][0],settled_at=report.get('settled_at'),peak_force=report['max_force'],max_cart=report['max_cart'],
              final_error_deg=report['final_angle_deg'],status='verified',has_control_plan=True,plan_kind='segmented' if plan.get('segments') else 'tracking',created_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
    data=dict(**meta,frames=frames,sample_dt=.02,design=analyze(plant,target=goal),verification=report,control_plan=plan)
    return _write(meta,data)

def _write(meta,data):
    ident=meta['id']
    with LOCK,disk_lock():
        ROOT.mkdir(exist_ok=True)
        temp=ROOT/(ident+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8');temp.replace(ROOT/(ident+'.json'))
        rows=[r for r in catalog() if r['id']!=ident];rows.append(meta)
        temp=ROOT/'index.tmp';temp.write_text(json.dumps(dict(schema_version=1,solutions=rows),ensure_ascii=False,indent=2),encoding='utf8');temp.replace(ROOT/'index.json')
    return meta

@contextmanager
def directory_lock(root,timeout=600,stale_seconds=300):
    """Directory lock for local filesystems; cluster solvers use per-case files."""
    root.mkdir(exist_ok=True);directory=root/'.write.lockdir';token=uuid.uuid4().hex;started=time.monotonic()
    while True:
        try:
            directory.mkdir()
            (directory/'owner.json').write_text(json.dumps(dict(token=token,pid=os.getpid(),host=socket.gethostname(),created_at=time.time())),encoding='utf8')
            break
        except (FileExistsError,PermissionError):
            try:
                if time.time()-directory.stat().st_mtime>stale_seconds:
                    directory.rename(root/('.write.lockdir.stale-'+uuid.uuid4().hex));continue
            except FileNotFoundError:continue
            except PermissionError:pass
            if time.monotonic()-started>timeout:raise TimeoutError('Shared repository lock timed out')
            time.sleep(.04)
    try:yield
    finally:
        try:
            owner=directory/'owner.json'
            if json.loads(owner.read_text(encoding='utf8')).get('token')==token:owner.unlink();directory.rmdir()
        except (FileNotFoundError,PermissionError):pass

@contextmanager
def disk_lock():
    ROOT.mkdir(exist_ok=True)
    if os.name!='nt':
        with directory_lock(ROOT):yield
        return
    with open(ROOT/'.write.lock','a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        import msvcrt
        msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
        try:yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)


def store_live(clip):
    p=Plant(Parameters(**clip['parameters']));goal=np.asarray(clip.get('target_angles',[0.]*p.n),dtype=float)
    frames=np.asarray(clip['frames'],dtype=float);target=float(clip.get('target',0))
    if p.n>5 or goal.shape!=(p.n,) or not np.isfinite(goal).all() or np.max(abs(np.sin(goal)))>1e-8:raise ValueError('目标必须是上下平衡姿态')
    if frames.ndim!=2 or frames.shape[1]!=p.dim+2 or not 60<=len(frames)<=20000 or not np.isfinite(frames).all():raise ValueError('记录数据不完整')
    if not np.all(np.diff(frames[:,0])>0):raise ValueError('记录时间戳必须严格递增')
    if np.max(abs(frames[:,1]))>p.p.rail+1e-8 or np.max(abs(frames[:,-1]))>p.p.max_force+1e-8:raise ValueError('记录超出物理边界')
    tail=frames[frames[:,0]>=frames[-1,0]-1]
    if len(tail)<20 or np.max(abs(wrap(tail[:,2:p.d+1]-goal)))>np.deg2rad(.5) or np.max(abs(tail[:,p.d+2:-1]))>.03 or np.max(abs(tail[:,1]-target))>.03:raise ValueError('记录末尾未连续稳定 1 秒')
    initial=frames[0,1:-1].copy();code=pattern(goal);normalized=initial.copy();normalized[1:p.d]=wrap(normalized[1:p.d])
    fingerprint=json.dumps([p.p.dict(),normalized.round(9).tolist(),code,target,'live'],sort_keys=True)
    ident=hashlib.sha256(fingerprint.encode()).hexdigest()[:24];start=frames[0,0];frames[:,0]-=start
    meta=dict(id=ident,order=p.n,title='我的成功实验 → '+label(code),pattern=code,target_label=label(code),initial=initial.tolist(),
              target_angles=goal.tolist(),target=target,parameters=p.p.dict(),source='实时成功记录',duration=float(frames[-1,0]),
              settled_at=max(0,float(clip.get('settled_at',start))-start),peak_force=float(np.max(abs(frames[:,-1]))),
              max_cart=float(np.max(abs(frames[:,1]))),final_error_deg=float(np.max(abs(wrap(tail[-1,2:p.d+1]-goal)))*180/np.pi),
              status='recorded',has_control_plan=False,created_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
    return _write(meta,dict(**meta,frames=frames.tolist(),sample_dt=float(clip.get('sample_dt',.01)),design=analyze(p,target=goal)))

def nearest_template(plant,initial,goal):
    rows=[r for r in catalog() if r['order']==plant.n and r['pattern']==pattern(goal) and r.get('has_control_plan',True) and r.get('plan_kind')!='segmented']
    if not rows:return None
    def distance(row):
        d=np.array(row['initial'])-initial;d[1:plant.d]=wrap(d[1:plant.d]);return float(np.sum(d*d))
    return read(min(rows,key=distance)['id'])['control_plan']

def seed_existing():
    root=ROOT.parent
    for n in range(1,6):
        path=root/'results'/f'verified-{n}.json';history=root/'results'/f'audit-{n}.npz'
        if path.exists() and history.exists():
            p=Plant(Parameters(n=n));plan=json.loads(path.read_text(encoding='utf8'));plan.setdefault('target_angles',[0.]*n)
            store(plan,p,np.load(history)['history'],title='完全下垂静止 → '+label('U'*n))
