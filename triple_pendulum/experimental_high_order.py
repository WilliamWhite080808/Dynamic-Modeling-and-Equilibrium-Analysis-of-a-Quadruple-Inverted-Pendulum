"""Experimental 6/7-link cart-only trials; does not advertise GUI support."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
from pathlib import Path
import json,time
import numpy as np
from .model import Plant,Parameters
from . import precomputed
from .planner import tracking_gains


def lift(source,n):
    old=np.asarray(source['states']);old_n=old.shape[1]//2-1;d=n+1
    states=np.zeros((len(old),2*d));states[:,0]=old[:,0];states[:,d]=old[:,old_n+1]
    for k in range(len(old)):
        states[k,1:d]=np.interp(np.linspace(0,1,n),np.linspace(0,1,old_n),old[k,1:old_n+1])
        states[k,d+1:]=np.interp(np.linspace(0,1,n),np.linspace(0,1,old_n),old[k,old_n+2:])
    return dict(duration=source['duration'],states=states.tolist(),forces=source['forces'])


def main():
    from .implicit_optimal import optimize as implicit
    from .optimal import optimize as explicit
    from .validate_plan import replay
    status={};path=Path('results/experimental-high-order-status.json')
    p=Plant(Parameters(n=5));source=precomputed.lookup(p,precomputed.hanging(p),[0.]*5)
    for n in (6,7):
        p=Plant(Parameters(n=n));warm=lift(source,n);solved=None
        for attempt in range(3):
            optimize=implicit if attempt%2==0 else explicit;duration=n+2.+attempt
            status[str(n)]=dict(status='optimizing',attempt=attempt,duration=duration);path.write_text(json.dumps(status),encoding='utf8')
            print('EXPERIMENT',n,attempt,duration,flush=True)
            try:
                result=optimize(p,precomputed.hanging(p),duration,round(duration/.025)+1,warm,max_iter=800,max_seconds=120,
                    target_angles=np.zeros(n),endpoint_angles=np.ones(n)*2*np.pi,compute_gains=False,seed=800+attempt)
                for spacing in [.025,.02,.015,.01,.0075]:
                    if not result['success']:break
                    if spacing<result['dt']-1e-10:
                        result=optimize(p,precomputed.hanging(p),duration,round(duration/spacing)+1,result,max_iter=700,max_seconds=180,
                            target_angles=np.zeros(n),endpoint_angles=np.ones(n)*2*np.pi,compute_gains=False)
                        if not result['success']:break
                    result['gains']=tracking_gains(p,result)
                    report=replay(p,result,total=duration+20);report.pop('history')
                    print('EXPERIMENT REPLAY',n,result['dt'],report['final_stable'],report['max_cart'],flush=True)
                    if report['final_stable'] and report['max_cart']<p.p.rail*.96 and report['max_tracking_error']<3:
                        result.update(success=True,parameters=p.p.dict(),verification=report);solved=result;break
                if solved:break
                if result.get('defect',1e9)<.05:warm=result
            except Exception as error:print('EXPERIMENT ERROR',repr(error),flush=True)
        if solved is None:
            status[str(n)]=dict(status='not_verified');path.write_text(json.dumps(status),encoding='utf8');break
        Path(f'results/experimental-high-order-{n}.json').write_text(json.dumps(solved),encoding='utf8')
        status[str(n)]=dict(status='verified',verification=solved['verification']);path.write_text(json.dumps(status),encoding='utf8');source=solved

if __name__=='__main__':main()
