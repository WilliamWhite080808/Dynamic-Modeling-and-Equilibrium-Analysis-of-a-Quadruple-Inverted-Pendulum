"""Independently test saved offline candidates, then refine their meshes gradually."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
import argparse
import json
from pathlib import Path
import numpy as np
from . import precomputed,repository
from .model import Plant,Parameters
from .planner import tracking_gains,densify_reference


def certify(plant,code,plan):
    from .validate_plan import replay
    if precomputed.statuses()[f'{plant.n}-{code}']['status']=='ready':return True
    plan.setdefault('reference_solver_success',plan.get('success',False))
    if not plan.get('gains'):plan['gains']=tracking_gains(plant,plan)
    report=replay(plant,plan,total=plan['duration']+20);history=report.pop('history')
    print('CANDIDATE REPLAY',code,plan['dt'],report['final_stable'],report['max_cart'],report['max_tracking_error'],flush=True)
    if not report['final_stable'] or report['max_cart']>=plant.p.rail*.96 or report['max_tracking_error']>=3:
        if plan['dt']>.0125:
            # Coarse interpolation of a rapidly changing A/B matrix can itself
            # make TVLQR fail. Recompute feedback on the resolved reference;
            # independent physical integration still decides admission.
            return certify(plant,code,densify_reference(plant,plan))
        return False
    plan.update(success=True,parameters=plant.p.dict(),verification=report)
    meta=repository.store(plan,plant,history,title='完全下垂静止 → '+repository.label(code))
    precomputed.put(plant,code,plan,report,meta['id'])
    print('CANDIDATE READY',plant.n,code,plan['duration'],report['max_force'],flush=True);return True


def main():
    from .implicit_optimal import optimize as implicit
    from .optimal import optimize as explicit
    parser=argparse.ArgumentParser();parser.add_argument('--order',type=int,default=5);parser.add_argument('--patterns',default='');args=parser.parse_args()
    plant=Plant(Parameters(n=args.order))
    for path in sorted((precomputed.ROOT/'candidates').glob(f'{args.order}-*.json')):
        code=path.stem.split('-')[1]
        if args.patterns and code not in args.patterns.split(','):continue
        if precomputed.statuses()[f'{plant.n}-{code}']['status']=='ready':continue
        warm=json.loads(path.read_text(encoding='utf8'))
        if warm['defect']>=1e-5:continue
        print('REFINING',code,warm['dt'],flush=True)
        if certify(plant,code,warm):continue
        endpoint=np.array(warm['states'][-1])[1:plant.d]
        for dt in [.035,.03,.025,.02,.015,.01,.0075]:
            if warm['dt']<=dt:continue
            for optimize in (implicit,explicit):
                try:
                    result=optimize(plant,precomputed.hanging(plant),warm['duration'],round(warm['duration']/dt)+1,warm,
                        max_iter=650,max_seconds=240,target_angles=repository.angles(code),endpoint_angles=endpoint,compute_gains=False)
                except Exception as error:
                    print('REFINE ERROR',repr(error),flush=True);result={'success':False,'defect':float('inf')};continue
                print('REFINE RESULT',code,result['dt'],result['defect'],flush=True)
                if result['success']:break
            if not result['success']:
                if result.get('defect',1e9)<.01 and result.get('terminal_error',1e9)<.001:certify(plant,code,result)
                break
            warm=result
            warm['parameters']=plant.p.dict()
            with repository.disk_lock():
                temporary=path.with_suffix('.refined.tmp');temporary.write_text(json.dumps(warm),encoding='utf8');temporary.replace(path)
            if certify(plant,code,warm):break

if __name__=='__main__':main()
