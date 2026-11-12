"""Resumable offline batch for all 57 hanging-to-equilibrium targets (orders 1..5)."""
import os
# Each target is a separate CPU process; avoid tiny BLAS solves spawning 16 threads.
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
from pathlib import Path
import json
import time
import numpy as np
from .model import Plant,Parameters
from . import precomputed,repository

def solve_target(order,code,round_index=0,method='mixed'):
    from .optimal import optimize as explicit_optimize
    from .implicit_optimal import optimize as implicit_optimize
    from .validate_plan import replay
    p=Plant(Parameters(n=order));initial=precomputed.hanging(p);goal=repository.angles(code)
    key=f'{order}-{code}';prior=precomputed.statuses()[key];attempts=prior.get('attempts',0)
    if prior['status']=='ready':return True
    ready=[r for r in repository.catalog() if r['order']==order and r.get('has_control_plan',True) and abs(r['initial'][0])<1e-9 and np.max(abs(np.array(r['initial'])[p.d:]))<1e-9 and np.max(abs(np.array(r['initial'])[1:p.d]-np.pi))<1e-9]
    ready.sort(key=lambda r:sum(a!=b for a,b in zip(r['pattern'],code)))
    neighbors=[repository.read(row['id'])['control_plan'] for row in ready[:8]]
    warm=neighbors[0] if neighbors else None
    checkpoint_path=precomputed.ROOT/'candidates'/f'{key}.json'
    checkpoint=None
    if checkpoint_path.exists():
        checkpoint=json.loads(checkpoint_path.read_text(encoding='utf8'))
        if checkpoint.get('parameters')==p.p.dict():warm=checkpoint
        else:checkpoint=None
    def save_candidate(result):
        if not np.isfinite(np.array(result['states'])).all():return
        result['parameters']=p.p.dict()
        with repository.disk_lock():
            if checkpoint_path.exists():
                old=json.loads(checkpoint_path.read_text(encoding='utf8'))
                def quality(item):
                    feasible=item.get('defect',1e9)<1e-5 and item.get('terminal_error',1e9)<1e-5
                    return (0,item['dt']) if feasible else (1,item.get('defect',1e9)*100+item.get('terminal_error',1e9))
                if old.get('parameters')==p.p.dict() and quality(old)<quality(result):return
            checkpoint_path.parent.mkdir(exist_ok=True);temp=checkpoint_path.with_suffix('.tmp')
            temp.write_text(json.dumps(result),encoding='utf8');temp.replace(checkpoint_path)
    last_error='尚未找到可验证的受限轨迹'
    # Distinct winding classes and horizons, not repeated runs from one failed guess.
    for search in range(5):
        optimize=implicit_optimize if method=='implicit' or (method=='mixed' and search%2) else explicit_optimize
        attempts+=1;duration=min(16.,order+3.+2*(search//2)+round_index)
        up_indices=[i for i,c in enumerate(code) if c=='U'];endpoint=np.array([2*np.pi if c=='U' else np.pi for c in code])
        if search>=2:
            for j,i in enumerate(up_indices):
                if (j+search+round_index)%2==0:endpoint[i]=0.
        guess=deepcopy(warm) if search%2 else None
        if search%2 and neighbors:
            guess=deepcopy(neighbors[(round_index*2+search//2)%len(neighbors)])
        if search==0 and checkpoint is not None:
            guess=checkpoint;duration=checkpoint['duration'];endpoint=np.asarray(checkpoint['states'][-1])[1:p.d]
        coarse=max(121,int(duration/.04)+1)
        precomputed.update(order,code,status='computing',attempts=attempts,phase='离线优化',duration=duration,iterations=0,worker_pid=os.getpid())
        try:
            result=optimize(p,initial,duration,coarse,guess,max_iter=700,max_seconds=80,seed=420+attempts,
                target_angles=goal,endpoint_angles=endpoint,compute_gains=False,
                progress=lambda i:precomputed.update(order,code,iterations=i))
            if not result['success']:
                last_error=f'配点残差 {result["defect"]:.3g}，尚未满足动力学约束'
                if result['defect']<.05:warm=result;save_candidate(result)
                continue
            warm=result;save_candidate(result)
            from .precompute_refine import certify
            if certify(p,code,result):return True
            fine=max(coarse,int(duration/(.02 if order<=2 else .0125))+1)
            precomputed.update(order,code,phase='细化轨迹与反馈控制器')
            for spacing in [.03,.0225,.015,duration/(fine-1)]:
                if spacing>=result['dt']-1e-10:continue
                result=optimize(p,initial,duration,round(duration/spacing)+1,result,max_iter=600,max_seconds=150,seed=420+attempts,target_angles=goal,endpoint_angles=endpoint,compute_gains=False)
                if result['defect']<.05:save_candidate(result)
                if not result['success']:break
                if certify(p,code,result):return True
            if not result['success']:last_error='高精度网格未通过约束校验';continue
            save_candidate(result)
            precomputed.update(order,code,phase='独立非线性闭环验收')
            report=replay(p,result,total=duration+(20 if order>=4 else 10));history=report.pop('history')
            if not report['final_stable'] or report['max_cart']>=p.p.rail*.96 or report['max_tracking_error']>=3:
                last_error=f'闭环未通过：末端误差 {report["final_angle_deg"]:.3g}°，行程 {report["max_cart"]:.3g} m';warm=result;continue
            result.update(verification=report,parameters=p.p.dict(),success=True)
            meta=repository.store(result,p,history,title='完全下垂静止 → '+repository.label(code))
            precomputed.put(p,code,result,report,meta['id'])
            print('READY',key,'time',duration,'force',round(report['max_force'],2),flush=True)
            return True
        except Exception as error:last_error=str(error)[-500:]
    precomputed.update(order,code,status='retry_pending',phase='待下一轮离线搜索',last_error=last_error,attempts=attempts)
    print('RETRY',key,last_error,flush=True)
    return False

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=2);parser.add_argument('--rounds',type=int,default=3);parser.add_argument('--orders',default='1,2,3,4,5')
    parser.add_argument('--patterns',default='');parser.add_argument('--method',choices=['explicit','implicit','mixed'],default='mixed')
    args=parser.parse_args();orders=set(map(int,args.orders.split(',')));precomputed.initialize();precomputed.import_verified()
    for round_index in range(args.rounds):
        pending=[r for r in precomputed.statuses().values() if r['order'] in orders and r['status']!='ready' and (not args.patterns or r['pattern'] in args.patterns.split(','))]
        pending.sort(key=lambda r:(r['order'],r['pattern'].count('U'),r['pattern']))
        if not pending:break
        print('OFFLINE ROUND',round_index+1,'pending',len(pending),flush=True)
        with ProcessPoolExecutor(max_workers=max(1,min(args.workers,4))) as executor:
            tasks=[executor.submit(solve_target,r['order'],r['pattern'],round_index,args.method) for r in pending]
            for task in as_completed(tasks):
                try:task.result()
                except Exception as error:print('BATCH ERROR',str(error),flush=True)
    for row in precomputed.catalog()['entries']:
        if row['order'] in orders and row['status']=='computing' and (not args.patterns or row['pattern'] in args.patterns.split(',')):
            precomputed.update(row['order'],row['pattern'],status='retry_pending',phase='本次批计算结束，仍待验证通过')
    result=precomputed.catalog();print('OFFLINE RESULT',result['ready'],'/',result['total'],flush=True)
    if any(r['status']!='ready' for r in result['entries'] if r['order'] in orders and (not args.patterns or r['pattern'] in args.patterns.split(','))):raise SystemExit(1)

if __name__=='__main__':main()
