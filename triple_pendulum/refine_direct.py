"""Extra searches for fourth-order direct transfers, never stitched admissions."""
import os
for k in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[k]='1'
import argparse,hashlib,json,subprocess,time,uuid
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from . import transitions,repository,precomputed
from .model import Plant,Parameters
from .direct_quality import intermediate_hold
from .precompute_equilibria import reverse_reference
from .planner import tracking_gains
from .validate_plan import replay
from .control import analyze

PROJECT=Path(__file__).resolve().parent.parent
OUT=PROJECT/'results/direct-refinement'
REMOTE='/data/wangqm/hmy/pendulum4_20261112'

def publish(plan,proof):
    payload=json.dumps(dict(plan=plan,proof=proof),ensure_ascii=False)
    script='ROOT='+repr(REMOTE)+'\nPAYLOAD='+repr(payload)+'''\nimport os,json,sys
from pathlib import Path
os.environ['PENDULUM_CLUSTER_MODE']='1';sys.path.insert(0,ROOT)
from triple_pendulum import transitions
from triple_pendulum.model import Plant,Parameters
data=json.loads(PAYLOAD);plan=data['plan'];proof=data['proof'];identity=plan['transition'];plant=Plant(Parameters(**plan['parameters']))
row=transitions.statuses()[transitions.key(4,identity['source'],identity['target'])]
assert plant.n==4 and not plan.get('route_waypoints') and not plan.get('segments')
if row['status']=='ready':print('ALREADY_READY')
else:print('PUBLISHED',transitions.admit(plant,identity['source'],identity['target'],plan,proof,[]))
'''
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','wqm',REMOTE+'/venv/bin/python','-u','-'],input=script,cwd=PROJECT,text=True,encoding='utf8',capture_output=True,timeout=80)
    if result.returncode:raise RuntimeError(result.stderr[-1200:])
    return result.stdout.strip()

def solve(source,target,send_remote=True,max_methods=2):
    from .optimal import optimize as explicit
    from .implicit_optimal import optimize as implicit
    OUT.mkdir(exist_ok=True);key=transitions.key(4,source,target);plant=Plant(Parameters(n=4))
    row=transitions.statuses()[key]
    if not row.get('route_waypoints'):return dict(key=key,status='already_direct')
    saved=OUT/(key+'.json')
    if saved.exists():
        plan=json.loads(saved.read_text(encoding='utf8'))
        if plan.get('direct_quality',{}).get('passed') and plan.get('verification',{}).get('final_stable') and len(plan.get('worker_verification',{}).get('individual',[]))==1:
            return dict(key=key,status='verified_direct',duration=plan['duration'],publication=publish(plan,plan['verification']) if send_remote else 'local_verified')
    initial=transitions.equilibrium(plant,source);goal=repository.angles(target)
    refs=[]
    if source=='DDDD':
        hanging=precomputed.lookup(plant,initial,goal)
        if hanging:refs.append((hanging,hanging['duration']*1.2))
    opposite=transitions.statuses()[transitions.key(4,target,source)]
    if opposite['status']=='ready' and not opposite.get('route_waypoints'):
        ref=reverse_reference(plant,transitions.lookup(plant,target,source),source,target);refs.append((ref,ref['duration']*1.15))
    route=transitions.lookup(plant,source,target)
    refs.extend([(route,route['duration']*.72),(route,route['duration']*.88),(route,route['duration']*.60)])
    refs.sort(key=lambda item:item[1]>11)
    failures=[];started_methods=0;record=dict(key=key,source=source,target=target)
    tried_path=OUT/(key+'.attempts.json');tried=json.loads(tried_path.read_text(encoding='utf8')) if tried_path.exists() else []
    for attempt,(ref,duration) in enumerate(refs):
        if not transitions.statuses()[key].get('route_waypoints'):return dict(key=key,status='already_direct')
        for method,optimize in [('explicit',explicit),('implicit',implicit)]:
            fingerprint=method+':'+str(round(duration,6))
            if fingerprint in tried or started_methods>=max_methods:continue
            started_methods+=1;tried.append(fingerprint);tried_path.write_text(json.dumps(tried),encoding='utf8')
            started=time.time();record=dict(key=key,source=source,target=target,attempt=attempt,method=method,duration=duration,status='optimizing',updated_at=started)
            (OUT/(key+'.progress.json')).write_text(json.dumps(record),encoding='utf8')
            print('DIRECT_SEARCH',key,method,round(duration,2),flush=True)
            try:
                result=optimize(plant,initial,duration,round(duration/.035)+1,ref,max_iter=1000,max_seconds=100,target_angles=goal,endpoint_angles=np.asarray(ref['states'][-1])[1:plant.d],initial_force=0.,force_rate=500.,force_fraction=.92,compute_gains=False)
                if result['defect']>.02 or result['terminal_error']>.001:raise ValueError('Coarse residual '+str(result['defect']))
                for spacing in (.022,.0125):
                    result=optimize(plant,initial,duration,round(duration/spacing)+1,result,max_iter=900,max_seconds=120,target_angles=goal,endpoint_angles=np.asarray(ref['states'][-1])[1:plant.d],initial_force=0.,force_rate=500.,force_fraction=.92,compute_gains=False)
                    if result['defect']>.02 or result['terminal_error']>.001:raise ValueError('Refinement residual '+str(result['defect']))
                result.update(success=True,strict_rest=True,force_rate=500.,parameters=plant.p.dict(),transition=dict(order=4,source=source,target=target))
                result['gains']=tracking_gains(plant,result)
                proof=replay(plant,result,total=duration+15);history=proof.pop('history')
                quality=intermediate_hold(plant,history[:,1:-1],.02,source,target)
                if not(proof['final_stable'] and proof['max_cart']<plant.p.rail*.96 and proof['max_force']<=120 and proof['max_force_rate']<=500.000001 and proof['max_tracking_error']<3 and quality['passed']):raise ValueError('Physical/directness verification failed '+str(dict(stable=proof['final_stable'],cart=proof['max_cart'],force=proof['max_force'],tracking=proof['max_tracking_error'],hold=quality)))
                result['verification']=proof;result['direct_quality']=quality
                fixture=OUT/(key+'.fixture.json');worker=OUT/(key+'.worker.json')
                fixture.write_text(json.dumps([dict(design=analyze(plant,target=goal),source_design=analyze(plant,target=repository.angles(source)),plan=result)]),encoding='utf8')
                run=subprocess.run(['node','tests/check-transfers.mjs',str(fixture.relative_to(PROJECT)),str(worker.relative_to(PROJECT))],cwd=PROJECT,text=True,capture_output=True,timeout=150)
                if run.returncode:raise ValueError('Worker verification failed: '+run.stderr[-700:])
                result['worker_verification']=json.loads(worker.read_text(encoding='utf8'));(OUT/(key+'.json')).write_text(json.dumps(result),encoding='utf8')
                publication=publish(result,proof) if send_remote else 'local_verified'
                record.update(status='verified_direct',duration=duration,publication=publication,updated_at=time.time());(OUT/(key+'.progress.json')).write_text(json.dumps(record),encoding='utf8');print('DIRECT_READY',json.dumps(record),flush=True);return record
            except Exception as error:
                failures.append(str(error)[-500:]);print('DIRECT_RETRY',key,failures[-1],flush=True)
    record.update(status='needs_more_search',failures=failures,updated_at=time.time());(OUT/(key+'.progress.json')).write_text(json.dumps(record),encoding='utf8');return record

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=2);parser.add_argument('--rounds',type=int,default=5);parser.add_argument('--max-methods',type=int,default=2);parser.add_argument('--pair');parser.add_argument('--no-publish',action='store_true');args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    for round_index in range(args.rounds):
        rows=[r for r in transitions.catalog(4)['entries'] if r.get('route_waypoints')]
        rows.sort(key=lambda r:(r['source']!='DDDD',r['target']!='UUUU',r['source'],r['target']))
        if args.pair:
            a,b=args.pair.split(':');rows=[r for r in rows if r['source']==a and r['target']==b]
        if not rows:break
        print('DIRECT_ROUND',round_index+1,'pending',len(rows),flush=True)
        with ProcessPoolExecutor(max_workers=max(1,min(4,args.workers))) as pool:
            futures=[pool.submit(solve,r['source'],r['target'],not args.no_publish,max(1,args.max_methods)) for r in rows]
            for future in as_completed(futures):
                try:print('FINISHED',json.dumps(future.result()),flush=True)
                except Exception as error:print('SEARCH_ERROR',repr(error),flush=True)

if __name__=='__main__':main()
