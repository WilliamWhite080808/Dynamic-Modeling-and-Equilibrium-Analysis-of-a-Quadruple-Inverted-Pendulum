"""Offline alternative: append a cart-only equilibrium transfer to a verified path.

This changes the optimizer's initial guess, never the simulated physical state.
Every concatenated path is independently integrated from hanging before admission.
"""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
    os.environ[name]='1'
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
import json
import numpy as np
from . import precomputed,repository
from .model import Plant,Parameters,wrap
from .planner import tracking_gains


def concatenate(plant,prefix,suffix,dt=None,compute_gains=True):
    if np.max(abs(np.asarray(prefix['states'][-1])-np.asarray(suffix['states'][0])))>1e-5:
        raise ValueError('Transfer initial state must equal the preceding reference endpoint')
    if abs(prefix['forces'][-1]-suffix['forces'][0])>1e-5:
        raise ValueError('Transfer force must be continuous at the join')
    # Preserve the certified prefix's mesh. Resampling a fast nonlinear spin onto
    # an unrelated mesh can introduce large reference defects between nodes.
    dt=prefix['dt'] if dt is None else dt
    duration=prefix['duration']+suffix['duration']
    nodes=round(duration/dt)+1;dt=duration/(nodes-1)
    def sample(plan,t):
        z=min(t/plan['dt'],len(plan['states'])-1)
        j=min(int(z),len(plan['states'])-2);a=z-j;h=plan['dt']
        x=np.array(plan['states'][j]);y=np.array(plan['states'][j+1])
        f=np.array(plan['derivatives'][j]);g=np.array(plan['derivatives'][j+1])
        state=(2*a**3-3*a*a+1)*x+(a**3-2*a*a+a)*h*f+(-2*a**3+3*a*a)*y+(a**3-a*a)*h*g
        force=(1-a)*plan['forces'][j]+a*plan['forces'][j+1]
        return state,force
    rows=[sample(prefix,t) if t<=prefix['duration'] else sample(suffix,t-prefix['duration']) for t in np.linspace(0,duration,nodes)]
    states=np.array([r[0] for r in rows]);forces=np.array([r[1] for r in rows])
    derivatives=plant.batch(states.copy(),forces.copy())
    h=dt;mid=(states[:-1]+states[1:])/2+h/8*(derivatives[:-1]-derivatives[1:])
    fm=plant.batch(mid.copy(),((forces[:-1]+forces[1:])/2).copy())
    defect=float(np.max(abs(states[1:]-states[:-1]-h/6*(derivatives[:-1]+4*fm+derivatives[1:]))))
    result=dict(initial=prefix['initial'],target_angles=suffix['target_angles'],duration=duration,dt=dt,
        states=states.tolist(),forces=forces.tolist(),derivatives=derivatives.tolist(),defect=defect,
        solver='verified swing-up + passive-joint equilibrium transfer',success=defect<1e-4)
    result['gains']=tracking_gains(plant,result) if result['success'] and compute_gains else []
    return result


def solve_transfer(order,code,max_sources=5):
    from .optimal import optimize as explicit
    from .implicit_optimal import optimize as implicit
    from .precompute_refine import certify
    plant=Plant(Parameters(n=order));goal=repository.angles(code)
    if precomputed.statuses()[f'{order}-{code}']['status']=='ready':return True
    sources=[r for r in precomputed.catalog(order)['entries'] if r['status']=='ready' and r['pattern']!=code]
    sources.sort(key=lambda r:(sum(a!=b for a,b in zip(r['pattern'],code)),r.get('duration',100)))
    for source in sources[:max_sources]:
        prefix=precomputed.lookup(plant,precomputed.hanging(plant),repository.angles(source['pattern']))
        if prefix is None:continue
        initial=np.array(prefix['states'][-1]);base=initial[1:plant.d]-wrap(initial[1:plant.d]-goal)
        candidate=precomputed.ROOT/'candidates'/f'transfer-{order}-{source["pattern"]}-{code}.json'
        def polish(warm,optimize=implicit):
            for spacing in [.03,.02,.015,.0125,prefix['dt']]:
                if spacing>=warm['dt']-1e-10:continue
                fine=optimize(plant,initial,warm['duration'],round(warm['duration']/spacing)+1,warm,
                    max_iter=650,max_seconds=150,target_angles=goal,endpoint_angles=np.asarray(warm['states'][-1])[1:plant.d],
                    compute_gains=False,initial_force=0)
                print('TRANSFER REFINE',code,fine['dt'],fine['defect'],flush=True)
                if not fine['success']:
                    if fine['defect']<.01 and fine['terminal_error']<.001:
                        if certify(plant,code,concatenate(plant,prefix,fine)):return True
                    return False
                candidate.write_text(json.dumps(fine),encoding='utf8');warm=fine
                if certify(plant,code,concatenate(plant,prefix,fine)):return True
            return False
        if candidate.exists():
            saved=json.loads(candidate.read_text(encoding='utf8'))
            if saved.get('success') and np.max(abs(np.asarray(saved['initial'])-initial))<1e-8:
                print('TRANSFER RESUME',code,saved['dt'],flush=True)
                if certify(plant,code,concatenate(plant,prefix,saved)) or polish(saved):return True
        for attempt in range(6):
            if precomputed.statuses()[f'{order}-{code}']['status']=='ready':return True
            endpoint=base.copy()
            if attempt%2:
                for j,c in enumerate(code):
                    if c!=source['pattern'][j]:endpoint[j]-=2*np.pi*np.sign(base[j]-initial[j])
            duration=4.+2*(attempt//2);optimize=implicit if attempt%2==0 else explicit
            continuation={'residual_homotopy':True} if attempt==0 else {}
            print('TRANSFER',order,source['pattern'],'->',code,'duration',duration,'attempt',attempt,flush=True)
            try:
                coarse=optimize(plant,initial,duration,round(duration/.04)+1,max_iter=500,max_seconds=45,
                    seed=600+attempt,target_angles=goal,endpoint_angles=endpoint,compute_gains=False,initial_force=0,**continuation)
                if not coarse['success']:
                    print('TRANSFER DEFECT',coarse['defect'],flush=True);continue
                candidate.write_text(json.dumps(coarse),encoding='utf8')
                # The admission criterion is the actual cart-force-only RK4
                # trajectory. An approximate reference can still be trackable.
                combined=concatenate(plant,prefix,coarse)
                if certify(plant,code,combined):return True
                if polish(coarse,optimize):return True
            except Exception as error:print('TRANSFER ERROR',repr(error),flush=True)
    return False


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--orders',default='4,5');parser.add_argument('--patterns',default='')
    parser.add_argument('--sources',type=int,default=3);parser.add_argument('--workers',type=int,default=1);args=parser.parse_args()
    for order in map(int,args.orders.split(',')):
        pending=[r for r in precomputed.catalog(order)['entries'] if r['status']!='ready' and (not args.patterns or r['pattern'] in args.patterns.split(','))]
        pending.sort(key=lambda r:-r['pattern'].count('U'))
        if args.workers<=1:
            for row in pending:solve_transfer(order,row['pattern'],args.sources)
        else:
            with ProcessPoolExecutor(max_workers=min(2,args.workers)) as pool:
                tasks=[pool.submit(solve_transfer,order,row['pattern'],args.sources) for row in pending]
                for task in as_completed(tasks):
                    try:task.result()
                    except Exception as error:print('TRANSFER TASK ERROR',repr(error),flush=True)

if __name__=='__main__':main()
