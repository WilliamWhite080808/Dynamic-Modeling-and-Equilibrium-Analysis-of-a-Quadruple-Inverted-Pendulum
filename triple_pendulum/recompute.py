"""Re-optimize certified motions into an isolated directory, never overwrite the bank."""
from pathlib import Path
import argparse,hashlib,json,time
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np
from . import transitions
from .model import Plant,Parameters
from .portfolio_fifth import method_options,METHODS


def one(row,destination,method='inverse-hs',max_seconds=75.,max_iter=600,cold=False):
    path=(transitions.ROOT/row['file']).resolve()
    if not path.is_relative_to(transitions.ROOT.resolve()):raise ValueError('Invalid certified source path')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Certified input checksum changed')
    template=json.loads(raw);plant=Plant(Parameters(**row['parameters']))
    from .optimal import optimize as explicit
    from .implicit_optimal import optimize as implicit
    from .validate_plan import replay
    optimize=implicit if method in ('inverse-hs','residual-continuation') else explicit
    endpoint=np.asarray(template['target_angles'])+2*np.pi*np.rint((np.asarray(template['states'][-1])[1:plant.d]-np.asarray(template['target_angles']))/(2*np.pi))
    started=time.monotonic()
    result=optimize(plant,np.asarray(template['initial']),template['duration'],len(template['states']),None if cold else template,
        max_iter=max_iter,max_seconds=max_seconds,target_angles=template['target_angles'],endpoint_angles=endpoint,
        initial_force=0.,force_rate=500.,force_fraction=1.,compute_gains=True,reference_weight=0. if cold else 1000.,**method_options(method))
    result.update(parameters=plant.p.dict(),source=row['source'],pattern=row['target'],force_rate=500.,strict_rest=True)
    verification={}
    if result['success'] and len(result.get('gains',[]))==len(result['states']):
        verification=replay(plant,result,total=result['duration']+15);verification.pop('history')
    passed=bool(verification.get('final_stable') and verification['max_cart']<plant.p.rail*.96 and verification['max_force']<=plant.p.max_force+1e-6 and verification['max_force_rate']<=500+1e-6)
    result.update(verification=verification,recomputed_from_sha256=row['sha256'],method=method,physical_recompute_passed=passed,worker_accepted=False)
    key=transitions.key(row['order'],row['source'],row['target']);target=Path(destination)/(key+'.json')
    if target.exists():raise ValueError('Refusing to overwrite an existing recomputation')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return dict(key=key,passed=passed,method=method,seconds=time.monotonic()-started,verification=verification,file=str(target))


def main():
    p=argparse.ArgumentParser();p.add_argument('--orders',default='1,2,3,4,5');p.add_argument('--all-ready',action='store_true');p.add_argument('--source');p.add_argument('--target');p.add_argument('--method',choices=METHODS,default='inverse-hs');p.add_argument('--workers',type=int,default=1);p.add_argument('--max-seconds',type=float,default=75);p.add_argument('--max-iter',type=int,default=600);p.add_argument('--cold',action='store_true');p.add_argument('--out',required=True);a=p.parse_args()
    orders={int(n) for n in a.orders.split(',')}
    if not orders or any(n not in range(1,6) for n in orders):p.error('Orders must be in 1..5')
    destination=Path(a.out).resolve();destination.mkdir(parents=True,exist_ok=False)
    ready=[r for r in transitions.statuses().values() if r['order'] in orders and r['status']=='ready']
    if not a.all_ready:
        ready=[r for r in ready if r['source']==(a.source or 'D'*r['order']) and r['target']==(a.target or 'U'*r['order'])]
    if not ready:p.error('No matching certified motions')
    rows=[]
    with ProcessPoolExecutor(max_workers=max(1,min(8,a.workers))) as pool:
        futures={pool.submit(one,r,destination,a.method,a.max_seconds,a.max_iter,a.cold):r for r in ready}
        for future in as_completed(futures):
            try:row=future.result()
            except Exception as error:
                r=futures[future];row=dict(key=transitions.key(r['order'],r['source'],r['target']),passed=False,error=str(error))
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    summary=dict(requested=len(ready),physical_passed=sum(r['passed'] for r in rows),bank_unchanged=True,new_worker_certification_required=True,rows=rows)
    (destination/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    if summary['physical_passed']!=summary['requested']:raise SystemExit(1)


if __name__=='__main__':main()
