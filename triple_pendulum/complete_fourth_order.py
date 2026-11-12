"""Certify continuous state/force trajectories through explicit intermediate poses.

The resulting paths retain every reference sample and a single TVLQR schedule.
The physical state is integrated continuously; waypoint poses are not resets.
Remote direct searches remain independent and can replace these longer paths.
"""
import os
for k in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[k]='1'
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib,json,time
from pathlib import Path
from . import transitions
from .model import Plant,Parameters
from .planner import tracking_gains
from .route_seeds import route_candidates,build_seed
from .remote_transitions import validate_and_admit,INCOMING,atomic_json,RESULTS

def certify_route(source,target,route):
    plant=Plant(Parameters(n=4));plan=build_seed(plant,route)
    plan.update(success=True,parameters=plant.p.dict(),force_rate=500.,strict_rest=True,
        transition=dict(order=4,source=source,target=target),route_waypoints=route,
        solver='Continuous passive-plant trajectory through certified equilibria')
    plan.pop('seed_kind',None);plan.pop('seed_waypoints',None)
    plan['gains']=tracking_gains(plant,plan)
    encoded=json.dumps(plan).encode('utf8');path=INCOMING/('continuous-'+transitions.key(4,source,target)+'.json');path.write_bytes(encoded)
    return validate_and_admit(str(path),dict(source=source,target=target,sha256=hashlib.sha256(encoded).hexdigest(),origin_host='continuous-verified-edges'))

def search_routes(source,target,paths):
    errors=[]
    for route in paths:
        try:
            result=certify_route(source,target,route);result['waypoints']=route;return result
        except Exception as error:
            errors.append(str(error));print('ALTERNATIVE',source,target,'via',route[1:-1],str(error)[-180:],flush=True)
    raise ValueError('No certified continuous route: '+str(errors[-1:]))

def main():
    INCOMING.mkdir(parents=True,exist_ok=True);rows=transitions.catalog(4)['entries']
    # Freeze the graph of direct, independently certified edges: no recursive
    # stitching of newly generated routes or detour through the down base.
    direct=[r for r in rows if not r.get('route_waypoints')]
    pending=[(r,route_candidates(direct,r['source'],r['target'])) for r in rows if r['status']!='ready']
    outcomes=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(search_routes,r['source'],r['target'],paths):r for r,paths in pending if paths}
        for future in as_completed(futures):
            row=futures[future]
            try:result=future.result();result.update(passed=True);print('ROUTE_READY',json.dumps(result),flush=True)
            except Exception as error:result=dict(source=row['source'],target=row['target'],passed=False,error=str(error));print('ROUTE_REJECTED',json.dumps(result),flush=True)
            outcomes.append(result);atomic_json(RESULTS/'fourth-order-continuous-paths.json',dict(updated_at=time.time(),outcomes=outcomes))
    print('TOTAL',transitions.catalog(4)['ready'],'/ 240',flush=True)

if __name__=='__main__':main()
