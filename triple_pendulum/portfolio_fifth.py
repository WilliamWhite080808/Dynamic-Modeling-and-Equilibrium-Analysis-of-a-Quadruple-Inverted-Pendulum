"""Four independent numerical methods per fifth-order case; Linux cluster only."""
import os
for _name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS','NUMBA_NUM_THREADS'):
    os.environ[_name]='1'
import argparse,json,time,uuid,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from itertools import product
import numpy as np
from . import transitions,repository
from .model import Plant,Parameters
from .precompute_equilibria import reverse_reference,certify

METHODS=('explicit-hs','inverse-hs','residual-continuation','rk4-shooting')

def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');temporary.replace(path)

def method_options(method):
    if method not in METHODS:raise ValueError('Unknown portfolio method')
    return {'residual_homotopy':True} if method=='residual-continuation' else {'transcription':'rk4'} if method=='rk4-shooting' else {}

def accepted(case):
    row=transitions.case_status(5,case['source'],case['target'])
    try:ack=json.loads((transitions.ROOT.parent/'portfolio/accepted'/(case['key']+'.json')).read_bytes())
    except (OSError,ValueError):return False
    return row['status']=='ready' and ack.get('local_physics_and_worker_accepted') is True and ack.get('sha256')==row.get('sha256')

class Published:
    def __init__(self,case,deadline):self.case,self.deadline=case,deadline
    def is_set(self):
        return time.time()>self.deadline or transitions.case_status(5,self.case['source'],self.case['target'])['status']=='ready'

def run_method(case,method,directory,hours):
    directory=Path(directory)/method;directory.mkdir(parents=True,exist_ok=True)
    log=(directory/'solver.log').open('a',buffering=1)
    os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
    print('METHOD_START',method,case['key'],time.time(),flush=True)
    status=directory/'progress.json';checkpoint=directory/'checkpoint.json'
    deadline=time.time()+hours*3600;cancel=Published(case,deadline)
    plant=Plant(Parameters(n=5));initial=transitions.equilibrium(plant,case['source']);goal=repository.angles(case['target'])
    from .optimal import optimize as explicit
    from .implicit_optimal import optimize as implicit
    optimize=implicit if method in ('inverse-hs','residual-continuation') else explicit
    options=method_options(method);warm=None;attempt=0
    try:
        prior=json.loads(status.read_bytes());attempt=prior.get('attempt',-1)+1
    except (OSError,ValueError):pass
    for path in (checkpoint,transitions.ROOT/'candidates'/(case['key']+'.json')):
        try:warm=json.loads(path.read_bytes());break
        except (OSError,ValueError):pass
    if warm is None:
        opposite=transitions.lookup(plant,case['target'],case['source'])
        if opposite is not None:warm=reverse_reference(plant,opposite,case['source'],case['target'])
    changed=[i for i,(a,b) in enumerate(zip(case['source'],case['target'])) if a!=b]
    windings=list(product((1,-1),repeat=len(changed)));index=METHODS.index(method)
    best_score=float('inf')
    while time.time()<deadline:
        if accepted(case):
            atomic(status,dict(method=method,state='accepted',attempt=attempt,time=time.time()));return method
        row=transitions.case_status(5,case['source'],case['target'])
        if row['status']=='ready':
            atomic(status,dict(method=method,state='waiting_local_verification',attempt=attempt,time=time.time()))
            time.sleep(5);continue
        duration=(7.,9.,11.,13.,15.,17.)[(attempt//len(windings)+index)%6]
        endpoint=initial[1:plant.d].copy()
        for i,sign in zip(changed,windings[(attempt+index*7)%len(windings)]):endpoint[i]+=sign*np.pi
        unchanged=[i for i in range(5) if i not in changed]
        if attempt>=len(windings) and unchanged:
            endpoint[unchanged[(attempt+index)%len(unchanged)]]+=2*np.pi*(-1 if attempt%2 else 1)
        guess=warm if attempt%3!=2 else None
        if guess is not None and attempt%3==0:
            duration=guess['duration'];last=np.asarray(guess['states'][-1])[1:plant.d]
            endpoint=np.asarray(goal)+2*np.pi*np.rint((last-np.asarray(goal))/(2*np.pi))
        fraction=(.66,.80,.90)[(attempt+index)%3]
        meta=dict(method=method,state='optimizing',attempt=attempt,duration=duration,case=case['key'])
        def progress(iteration):atomic(status,dict(meta,iteration=iteration,time=time.time()))
        progress(0)
        try:
            result=optimize(plant,initial,duration,round(duration/.03)+1,guess,max_iter=1600,
                seed=13001+index*1009+attempt*19,target_angles=goal,endpoint_angles=endpoint,
                initial_force=0.,force_rate=500.,compute_gains=False,force_fraction=fraction,
                max_seconds=240 if method=='residual-continuation' else 150,cancel=cancel,progress=progress,**options)
            if cancel.is_set():continue
            score=result['defect']+10*result['terminal_error']
            if np.isfinite(score) and score<best_score:
                best_score=score;atomic(directory/'best-numerical-iterate.json',result)
                if result['defect']<.1 and result['terminal_error']<.01:
                    warm=deepcopy(result);atomic(checkpoint,warm)
            for spacing in (None,.02,.0125,.008):
                if cancel.is_set():break
                if spacing is not None:
                    if not result['success']:break
                    result=optimize(plant,initial,duration,round(duration/spacing)+1,result,max_iter=1400,
                        target_angles=goal,endpoint_angles=endpoint,initial_force=0.,force_rate=500.,
                        compute_gains=False,force_fraction=fraction,max_seconds=180,cancel=cancel,
                        **({'transcription':'rk4'} if method=='rk4-shooting' else {}))
                if result['defect']<.02 and result['terminal_error']<.001:
                    warm=deepcopy(result);atomic(checkpoint,warm)
                    result['portfolio']=dict(method=method,attempt=attempt,run=Path(directory).parents[1].name)
                    import fcntl
                    lock=transitions.ROOT.parent/'portfolio/locks'/(case['key']+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
                    with lock.open('a') as handle:
                        fcntl.flock(handle,fcntl.LOCK_EX)
                        if transitions.case_status(5,case['source'],case['target'])['status']=='ready':break
                        if certify(plant,case['source'],case['target'],result):
                            print('CANDIDATE_PUBLISHED',method,case['key'],flush=True);break
        except InterruptedError:pass
        except Exception as error:
            print('ATTEMPT_ERROR',type(error).__name__,str(error)[-800:],flush=True)
            atomic(status,dict(meta,state='retry',error=str(error)[-800:],time=time.time()))
        attempt+=1
    atomic(status,dict(method=method,state='budget_ended',attempt=attempt,time=time.time()))
    return method

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--case-index',type=int);p.add_argument('--case-indices');p.add_argument('--hours',type=float,default=7.5);args=p.parse_args()
    root=Path(__file__).resolve().parent.parent
    assert root==Path('/data/wangqm/hmy/pendulum5_20261112') and os.environ.get('PENDULUM_CLUSTER_MODE')=='1'
    indices=list(map(int,args.case_indices.split(':'))) if args.case_indices else [args.case_index]
    assert indices and None not in indices and len(indices)==len(set(indices))
    assert len(indices)*4<=len(Path(os.environ['PBS_NODEFILE']).read_text().splitlines())
    manifest=json.loads(Path(args.manifest).read_bytes());cases=[manifest['cases'][i] for i in indices]
    print('GROUP_START',[c['key'] for c in cases],METHODS,os.environ.get('PBS_JOBID'),flush=True)
    transitions.initialize();transitions.search_manifest()
    plant=Plant(Parameters(n=5));plant.rk4(transitions.equilibrium(plant,'DDDDD'),0.,.001)
    print('WARMUP_OK',time.time(),flush=True)
    with ProcessPoolExecutor(max_workers=4*len(cases)) as pool:
        futures=[]
        for case in cases:
            directory=root/'portfolio'/manifest['run']/case['key'];directory.mkdir(parents=True,exist_ok=True)
            futures.extend(pool.submit(run_method,case,method,directory,args.hours) for method in METHODS)
        for future in futures:print('METHOD_END',future.result(),flush=True)
    print('GROUP_END',[(c['key'],accepted(c)) for c in cases],flush=True)

if __name__=='__main__':main()
