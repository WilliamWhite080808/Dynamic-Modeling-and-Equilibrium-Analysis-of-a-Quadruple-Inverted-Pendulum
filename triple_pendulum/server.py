"""Local-only web UI and scientific design / planning service."""
import os
# These 4–12 dimensional designs run faster without spawning a BLAS pool for
# every small matrix operation, especially while offline searches use the CPU.
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import uuid
import time
import threading
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .model import Plant, Parameters, wrap
from .control import analyze
from .planner import plan
from .planning_service import certified_plan
from . import repository,precomputed,transitions

ROOT=Path(__file__).resolve().parent.parent
RECORDINGS=ROOT/'recordings'
MAX_RECORDING_BYTES=512*1024*1024
app=FastAPI(title='Pendulum Lab')
@app.post('/api/recordings')
async def store_recording(request:Request):
    mime=request.headers.get('content-type','').split(';')[0]
    if mime not in ('video/webm','video/mp4'):raise HTTPException(415,'仅支持核心区域录制文件')
    RECORDINGS.mkdir(exist_ok=True);ident=uuid.uuid4().hex;extension='.mp4' if mime=='video/mp4' else '.webm'
    temporary=RECORDINGS/(ident+'.tmp');size=0
    try:
        with temporary.open('wb') as file:
            async for block in request.stream():
                size+=len(block)
                if size>MAX_RECORDING_BYTES:raise HTTPException(413,'本机副本过大，请使用文件保存入口')
                file.write(block)
        if not size:raise HTTPException(400,'录制文件为空')
        name=ident+extension;temporary.replace(RECORDINGS/name)
        return dict(id=name,url='/api/recordings/'+name,bytes=size)
    except BaseException:
        temporary.unlink(missing_ok=True);raise

@app.get('/api/recordings/{ident}')
def recording_file(ident:str):
    stem=ident.split('.')[0]
    if len(stem)!=32 or any(c not in '0123456789abcdef' for c in stem) or ident not in (stem+'.webm',stem+'.mp4'):raise HTTPException(404,'录制文件不存在')
    path=RECORDINGS/ident
    if not path.is_file():raise HTTPException(404,'录制文件不存在')
    return FileResponse(path,media_type='video/mp4' if ident.endswith('.mp4') else 'video/webm',filename='pendulum-core-'+ident)
@app.middleware('http')
async def fresh_local_assets(request,call_next):
    response=await call_next(request)
    if request.url.path=='/' or request.url.path.endswith(('.html','.css','.js')):response.headers['Cache-Control']='no-store'
    return response
pool=ThreadPoolExecutor(max_workers=1)
jobs={}
JOB_LOCK=threading.RLock()

def run_job(job,plant,initial,duration,seed,target_angles):
    job["started"]=time.perf_counter()
    try:
        return certified_plan(plant,initial,duration,seed,job["cancel"],lambda info:job.update(info),target_angles)
    except InterruptedError:
        job["phase"]="已取消"
        return {"success":False,"cancelled":True}



@app.post('/api/design')
def design(body:dict):
    try:
        p=Parameters(**body.get('parameters',{}))
        if p.n>5: raise ValueError('Interactive orders are validated up to 5')
        plant=Plant(p);goal=repository.angles(body.get('pattern','U'*p.n))
        if len(goal)!=p.n:raise ValueError('目标维度与阶数不匹配')
        data=analyze(plant,body.get('sensor','full_state'),float(body.get('aggressive',1)),goal)
        data['precomputed_catalog']=precomputed.catalog(p.n)
        data['hanging_plan']=precomputed.lookup(plant,body.get('initial',precomputed.hanging(plant)),goal)
        return data
    except Exception as e: raise HTTPException(422,str(e))


@app.post('/api/plan')
def start_plan(body:dict):
    with JOB_LOCK:return _start_plan(body)

def _start_plan(body:dict):
    try:
        p=Parameters(**body['parameters']); plant=Plant(p); initial=np.asarray(body['state'],dtype=float)
        if p.n>5 or initial.shape!=(plant.dim,) or not np.isfinite(initial).all(): raise ValueError('Invalid planning state')
        target_angles=repository.angles(body.get('pattern','U'*p.n))
        if len(target_angles)!=p.n:raise ValueError('目标维度与摆杆阶数不匹配')
        duration=float(np.clip(body.get('duration',p.n+2),2,12)); seed=int(body.get('seed',1))
        client=str(body.get('client_id','legacy'))[:128]
        ident=str(uuid.UUID(body['request_id'])) if body.get('request_id') else str(uuid.uuid4())
        if ident in jobs:return {'id':ident}
        for old in jobs.values():
            if old['client']==client and not old['future'].done():old['cancel'].set()
        job={'cancel':threading.Event(),'client':client,'phase':'排队等待，旧任务正在退出','started':time.perf_counter()}
        job['future']=pool.submit(run_job,job,plant,initial,duration,seed,target_angles)
        jobs[ident]=job
        for key in list(jobs):
            if len(jobs)>30 and key!=ident and jobs[key]['future'].done():del jobs[key]
        return {'id':ident}
    except Exception as e: raise HTTPException(422,str(e))


@app.delete('/api/plan/{ident}')
def cancel_plan(ident:str):
    if ident in jobs:
        jobs[ident]['cancel'].set();jobs[ident]['future'].cancel()
    return {'status':'cancelled'}


@app.get('/api/plan/{ident}')
def get_plan(ident:str):
    if ident not in jobs: raise HTTPException(404,'Unknown job')
    job=jobs[ident];future=job['future']
    if job['cancel'].is_set():return {'status':'cancelled'}
    if not future.done():return {'status':'computing','phase':job['phase'],'iterations':job.get('iterations',0),'search':job.get('search',0),'elapsed':time.perf_counter()-job['started']}
    try:return {'status':'done','plan':future.result()}
    except Exception as e:return {'status':'error','error':str(e)}


@app.get('/api/replays/{order}')
def success_replay(order:int):
    if order not in range(1,6):raise HTTPException(422,'Only orders 1..5 are available')
    path=ROOT/'results'/f'audit-{order}.npz'
    if not path.exists():raise HTTPException(404,'Recorded success not available')
    data=json.loads((ROOT/'results'/f'verified-{order}.json').read_text(encoding='utf8'))
    history=np.load(path)['history']
    # These are independently integrated true states, not collocation references.
    frames=[[0.,*data['initial'],0.]]+[[float(row[0]+.001),*row[1:].tolist()] for row in history]
    return dict(order=order,parameters=data['parameters'],design=analyze(Plant(Parameters(**data['parameters']))),frames=frames,
                duration=frames[-1][0],settled_at=data['verification'].get('settled_at',data['duration']),source='验证成功实录',sample_dt=.02)


@app.get('/api/repository')
def solution_catalog(order:int=3,pattern:str=''):
    if order not in range(1,6):raise HTTPException(422,'Only orders 1..5 are supported')
    rows=[row for row in repository.catalog() if row['order']==order and (not pattern or row['pattern']==pattern)]
    coverage={code:sum(row['pattern']==code for row in repository.catalog() if row['order']==order) for code in (transitions.patterns(order) if order<=4 else repository.patterns(order))}
    return {'solutions':sorted(rows,key=lambda row:row['created_at'],reverse=True),'coverage':coverage,'directory':'trajectory_repository'}


@app.get('/api/repository/{ident}')
def get_solution(ident:str):
    try:
        data=repository.read(ident);data.pop('control_plan',None);return data
    except (ValueError,FileNotFoundError):raise HTTPException(404,'Solution not found')


@app.post('/api/repository/record')
def record_live(body:dict):
    try:return repository.store_live(body)
    except (ValueError,KeyError,TypeError) as e:raise HTTPException(422,str(e))


@app.get('/api/health')
def health(): return {'status':'ok','orders':[1,2,3,4,5]}


@app.get('/api/precomputed')
def precomputed_catalog(order:int|None=None):
    if order is not None and order not in range(1,6):raise HTTPException(422,'Only orders 1..5 are supported')
    return precomputed.catalog(order)


@app.get('/api/transitions')
def transition_catalog(order:int|None=None):
    if order is not None and order not in range(1,6):raise HTTPException(422,'稳态互转仅支持 1～5 阶')
    return transitions.catalog(order)


@app.post('/api/transition')
def transition_plan(body:dict):
    try:
        p=Plant(Parameters(**body['parameters']));source=body['source'];target=body['target']
        if p.n not in range(1,6):raise ValueError('稳态互转仅支持 1～5 阶')
        expected=transitions.equilibrium(p,source)
        state=expected if body.get('jump_to_start') is True else np.asarray(body['state'],dtype=float)
        if state.shape!=(p.dim,) or not np.isfinite(state).all():raise ValueError('无效物理状态')
        if np.max(abs(wrap(state[1:p.d]-expected[1:p.d])))>.025 or abs(state[0])>.05 or np.max(abs(state[p.d:]))>.06:raise ValueError('请先回中并保持起点稳态')
        plan=transitions.lookup(p,source,target)
        if plan is None:raise ValueError('该参数的转场尚未通过离线验收')
        plan['pattern']=target
        return dict(plan=plan,design=analyze(p,'full_state',target=repository.angles(target)))
    except (ValueError,KeyError,TypeError) as error:raise HTTPException(422,str(error))


app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')


def main():
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8765,log_level='warning')


if __name__=='__main__': main()
