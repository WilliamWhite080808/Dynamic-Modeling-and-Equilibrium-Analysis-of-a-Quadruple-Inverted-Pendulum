"""Offline direct pose-to-pose planning, including 240 fourth-order transfers."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
from itertools import product
from pathlib import Path
import argparse,json,uuid
import numpy as np
from . import transitions,precomputed,repository
from .model import Plant,Parameters,wrap
from .planner import tracking_gains
from .validate_plan import replay

def shard_keys(rows,count,index):
    if not 0<=index<count:raise ValueError('Invalid shard index')
    keys=sorted(transitions.key(r['order'],r['source'],r['target']) for r in rows)
    return set(keys[index::count])

def checkpoint_write(path,data):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(data),encoding='utf8');temporary.replace(path)


def reverse_reference(plant,plan,source,target):
    result=deepcopy(plan);x=np.asarray(plan['states'])[::-1].copy();x[:,plant.d:]*=-1
    initial=transitions.equilibrium(plant,source)
    x[:,:plant.d]+=initial[:plant.d]-x[0,:plant.d]
    u=np.asarray(plan['forces'])[::-1].copy()-2*plant.p.cart_damping*np.asarray(plan['states'])[::-1,plant.d]
    u[0]=0;u[-1]=0
    result.update(initial=initial.tolist(),target_angles=repository.angles(target),states=x.tolist(),forces=u.tolist(),
        derivatives=plant.batch(x.copy(),u.copy()).tolist(),gains=[])
    return result


def certify(p,source,target,plan):
    if transitions.statuses()[transitions.key(p.n,source,target)]['status']=='ready':return True
    plan.update(initial=transitions.equilibrium(p,source).tolist(),target_angles=repository.angles(target),force_rate=transitions.RATE,strict_rest=True)
    if not plan.get('gains'):plan['gains']=tracking_gains(p,plan)
    report=replay(p,plan,total=plan['duration']+15);history=report.pop('history')
    if transitions.admit(p,source,target,plan,report,history):
        print('READY',p.n,source,'->',target,'T',plan['duration'],'force',round(report['max_force'],2),flush=True);return True
    return False


def solve_pair(n,source,target,round_index=0):
    from .implicit_optimal import optimize as implicit
    from .optimal import optimize as explicit
    p=Plant(Parameters(n=n));initial=transitions.equilibrium(p,source);goal=np.array(repository.angles(target))
    if transitions.statuses()[transitions.key(n,source,target)]['status']=='ready':return True
    transitions.update(n,source,target,status='computing',phase='离线直接转场优化')
    warm=None;checkpoint=transitions.ROOT/'candidates'/f'{n}-{source}-{target}.json';checkpoint.parent.mkdir(exist_ok=True)
    if checkpoint.exists():
        try:warm=json.loads(checkpoint.read_text(encoding='utf8'))
        except (OSError,ValueError):print('CHECKPOINT_RECOVERY',n,source,target,flush=True)
    if source=='D'*n:
        template=precomputed.lookup(p,initial,goal)
        if template is not None:
            if certify(p,source,target,deepcopy(template)):return True
            if warm is None:warm=template
    if target=='D'*n:
        template=precomputed.lookup(p,precomputed.hanging(p),repository.angles(source))
        if template is not None:
            candidate=reverse_reference(p,template,source,target)
            if certify(p,source,target,candidate):return True
            if warm is None:warm=candidate
    changed=[i for i,(a,b) in enumerate(zip(source,target)) if a!=b]
    windings=list(product((1,-1),repeat=len(changed)))
    last_error='尚未找到通过闭环验收的直接转场'
    opposite_tried=None
    for attempt in range(8):
        rows=transitions.statuses()
        if rows[transitions.key(n,source,target)]['status']=='ready':return True
        opposite=rows[transitions.key(n,target,source)];opposite_guess=False
        if n>=4 and not(attempt==0 and warm is not None) and opposite['status']=='ready' and opposite.get('sha256')!=opposite_tried:
            opposite_tried=opposite['sha256'];reference=transitions.lookup(p,target,source)
            if reference is not None:
                warm=reverse_reference(p,reference,source,target);opposite_guess=True
        optimize=implicit if attempt%2==0 else explicit
        duration=n+2.+2*(attempt//len(windings))+round_index
        duration=min(duration,11.)
        endpoint=initial[1:p.d].copy()
        for i,sign in zip(changed,windings[attempt%len(windings)]):endpoint[i]+=sign*np.pi
        if attempt>=max(4,len(windings)):
            unchanged=[i for i in range(n) if i not in changed]
            if unchanged:endpoint[unchanged[(attempt+round_index)%len(unchanged)]]+=2*np.pi*(-1 if attempt%2 else 1)
        guess=warm if warm is not None and (attempt%2==0 or attempt>=4) else None
        if (attempt==0 or opposite_guess) and warm is not None:duration=warm['duration'];endpoint=np.array(warm['states'][-1])[1:p.d];guess=warm
        try:
            transitions.update(n,source,target,attempt=attempt,phase='直接转场配点求解',duration=duration,iterations=0)
            result=optimize(p,initial,duration,round(duration/.03)+1,guess,max_iter=900 if n>=4 else 650,max_seconds=75 if n>=4 else 45,
                seed=900+attempt+round_index*11,target_angles=goal,endpoint_angles=endpoint,initial_force=0.,force_rate=transitions.RATE,compute_gains=False,
                progress=lambda i:transitions.update(n,source,target,iterations=i))
            if result['defect']<.02 and result['terminal_error']<.001:
                warm=deepcopy(result);checkpoint_write(checkpoint,warm)
                if certify(p,source,target,result):return True
            if not result['success']:last_error=f'配点残差 {result["defect"]:.3g}';continue
            for spacing in (.02,.0125,.008):
                if result['dt']<=spacing+1e-10:continue
                transitions.update(n,source,target,phase='细化直接转场与独立验收')
                result=optimize(p,initial,duration,round(duration/spacing)+1,result,max_iter=800 if n>=4 else 600,max_seconds=90 if n>=4 else 60,
                    target_angles=goal,endpoint_angles=endpoint,initial_force=0.,force_rate=transitions.RATE,compute_gains=False)
                if result['defect']<.02 and result['terminal_error']<.001:
                    warm=deepcopy(result);checkpoint_write(checkpoint,warm)
                    if certify(p,source,target,result):return True
                if not result['success']:break
        except Exception as error:last_error=str(error)[-350:]
    transitions.update(n,source,target,status='retry_pending',phase='下一轮继续搜索',last_error=last_error)
    print('RETRY',n,source,target,last_error,flush=True);return False


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=3);parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--orders',default='1,2,3,4');parser.add_argument('--start-round',type=int,default=0)
    parser.add_argument('--shards',type=int,default=1);parser.add_argument('--shard-index',type=int,default=0);args=parser.parse_args()
    orders=[int(v) for v in args.orders.split(',')]
    if not orders or any(n not in range(1,transitions.MAX_ORDER+1) for n in orders):parser.error('Orders must be in 1..4')
    if not 0<=args.shard_index<args.shards:parser.error('Invalid shard index')
    transitions.initialize()
    eligible=[r for r in transitions.catalog()['entries'] if r['order'] in orders]
    selected=shard_keys(eligible,args.shards,args.shard_index)
    workers=args.workers
    if os.environ.get('PBS_NODEFILE'):
        workers=min(workers,len(Path(os.environ['PBS_NODEFILE']).read_text().splitlines()))
    print('SHARD',args.shard_index,'/',args.shards,'tasks',len(selected),'workers',workers,flush=True)
    # Compile the true RK4 dynamics once before the Linux workers fork.
    warm_plant=Plant(Parameters(n=orders[0]));warm_plant.rk4(transitions.equilibrium(warm_plant,'D'*orders[0]),0.,.001)
    for round_index in range(args.start_round,args.start_round+args.rounds):
        pending=[r for r in transitions.catalog()['entries'] if transitions.key(r['order'],r['source'],r['target']) in selected and r['status']!='ready']
        if not pending:break
        pending.sort(key=lambda r:(r['order'],sum(a!=b for a,b in zip(r['source'],r['target']))))
        print('ROUND',round_index+1,'pending',len(pending),flush=True)
        with ProcessPoolExecutor(max_workers=min(64,max(1,workers))) as pool:
            futures=[pool.submit(solve_pair,r['order'],r['source'],r['target'],round_index) for r in pending]
            for future in as_completed(futures):
                try:future.result()
                except Exception as error:print('PAIR ERROR',repr(error),flush=True)
    rows=[r for r in transitions.catalog()['entries'] if transitions.key(r['order'],r['source'],r['target']) in selected]
    print('RESULT',sum(r['status']=='ready' for r in rows),'/',len(rows),flush=True)

if __name__=='__main__':main()
