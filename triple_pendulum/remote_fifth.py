"""Synchronize fifth-order cluster candidates; admit only independently verified plans."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib,json,re,subprocess,time
from pathlib import Path,PurePosixPath
from . import transitions,repository,remote_transitions as common

PROJECT=Path(__file__).resolve().parent.parent
INCOMING=PROJECT/'results/remote-n5'
STATUS=PROJECT/'results/fifth-order-remote.json'

def remote_snapshot(root,seen,rejected):
    code='ROOT='+repr(root)+'\nSEEN='+repr(seen)+'\nREJECTED='+repr(rejected)+'''\nimport os,sys,json,re,subprocess,time,tarfile,uuid
from pathlib import Path
root=Path(ROOT);os.chdir(root);sys.path.insert(0,str(root))
os.environ.update(PENDULUM_CLUSTER_MODE='1',PYTHONDONTWRITEBYTECODE='1',NUMBA_CACHE_DIR=str(root/'cache/numba'),TMPDIR=str(root/'tmp'),XDG_CACHE_HOME=str(root/'cache'))
from triple_pendulum import transitions
transitions.initialize()
meta=json.loads((root/'job.json').read_text())
result=subprocess.run(['/opt/tsce4/torque6/bin/qstat','-f']+meta['job_ids'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=20)
jobs=[]
for job_id in meta['job_ids']:
    block=next((b for b in result.stdout.split('Job Id:') if b.lstrip().startswith(job_id)),'')
    state=re.search(r'job_state = (\\w)',block);node=re.search(r'exec_host = ([^\\n]+)',block)
    jobs.append(dict(job_id=job_id,state=state.group(1) if state else 'finished_or_unknown',node=node.group(1).split('/')[0] if node else None))
for key,digest in REJECTED.items():
    assert re.fullmatch('5-[UD]{5}-[UD]{5}',key)
    path=transitions.ROOT/'rejections'/(key+'.json');temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(dict(sha256=digest)));temporary.replace(path)
rows=transitions.statuses();transitions._write(rows)
portfolio=root/'portfolio/active.json'
if portfolio.exists():
    portfolio_cases={r['key'] for r in json.loads(portfolio.read_text())['cases']}
    accepted=root/'portfolio/accepted';accepted.mkdir(parents=True,exist_ok=True)
    for key,digest in SEEN.items():
        if key not in portfolio_cases or rows.get(key,{}).get('sha256')!=digest:continue
        receipt=accepted/(key+'.json')
        try:old_receipt=json.loads(receipt.read_text())
        except (OSError,ValueError):old_receipt={}
        if old_receipt.get('sha256')!=digest:
            temporary=receipt.with_name(receipt.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps(dict(sha256=digest,local_physics_and_worker_accepted=True,time=time.time())))
            temporary.replace(receipt)
entries=[row for row in rows.values() if row['order']==5]
download=[row for row in entries if row['status']=='ready' and SEEN.get('5-'+row['source']+'-'+row['target'])!=row['sha256']]
archive=None
if download:
    archive=root/'exports'/('batch-'+uuid.uuid4().hex+'.tar.gz')
    with tarfile.open(str(archive),'w:gz') as tar:
        for row in download:tar.add(str(transitions.ROOT/row['file']),arcname=row['file'])
print(json.dumps(dict(metadata=meta,jobs=jobs,entries=entries,download=download,archive=str(archive) if archive else None,remote_ready=sum(row['status']=='ready' for row in entries))))
'''
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','wqm',root+'/venv/bin/python','-B','-u','-'],input=code,cwd=PROJECT,text=True,encoding='utf8',capture_output=True,timeout=90)
    if result.returncode:raise RuntimeError(result.stderr[-2000:] or result.stdout[-2000:])
    return json.loads(result.stdout)

def validate_candidate(path,row):
    from .model import Plant,Parameters
    from .control import analyze
    from .validate_plan import replay
    from .direct_quality import intermediate_hold
    plan=json.loads(Path(path).read_text(encoding='utf8'));plant=Plant(Parameters(**plan['parameters']))
    identity=dict(order=5,source=row['source'],target=row['target'])
    if plant.n!=5 or plan.get('transition')!=identity or plan.get('segments') or plan.get('route_waypoints'):raise ValueError('Expected a single direct fifth-order trajectory')
    report=replay(plant,plan,total=plan['duration']+15);history=report.pop('history')
    if not report['final_stable']:raise ValueError('Independent physical integration did not settle')
    quality=intermediate_hold(plant,history[:,1:-1],.02,row['source'],row['target'])
    if not quality['passed']:raise ValueError('Intermediate equilibrium stop: '+str(quality))
    plan['direct_quality']=quality
    prefix=INCOMING/(transitions.key(5,row['source'],row['target'])+'-'+row['sha256'][:12])
    fixture=prefix.with_suffix('.fixture.json');proof=prefix.with_suffix('.worker.json')
    fixture.write_text(json.dumps([dict(design=analyze(plant,'full_state',target=repository.angles(row['target'])),source_design=analyze(plant,'full_state',target=repository.angles(row['source'])),plan=plan)]),encoding='utf8')
    result=subprocess.run(['node','tests/check-transfers.mjs',str(fixture.relative_to(PROJECT)),str(proof.relative_to(PROJECT))],cwd=PROJECT,text=True,capture_output=True,timeout=180)
    if result.returncode:raise ValueError('Actual page Worker rejected candidate: '+(result.stderr or result.stdout)[-1800:])
    plan['worker_verification']=json.loads(proof.read_text(encoding='utf8'))
    plan['remote_provenance']=dict(host='wqm',sha256=row['sha256'])
    if not transitions.admit(plant,row['source'],row['target'],plan,report,history):raise ValueError('Rail, force, slew or tracking check failed')
    return dict(source=row['source'],target=row['target'],duration=plan['duration'],max_cart=report['max_cart'],max_force=report['max_force'])

def full_audit():
    from .model import Plant,Parameters
    from .control import analyze
    bank=transitions.catalog(5)
    if bank['ready']!=992:return False
    signature=transitions.bank_signature(order=5);proof=PROJECT/'results/fifth-order-worker-audit.json'
    if proof.exists():
        prior=json.loads(proof.read_text(encoding='utf8'))
        if prior.get('passed') and prior.get('bank_sha256')==signature:return True
    plant=Plant(Parameters(n=5));designs={pose:analyze(plant,'full_state',target=repository.angles(pose)) for pose in transitions.patterns(5)}
    fixtures=[dict(design=designs[row['target']],source_design=designs[row['source']],plan=transitions.lookup(plant,row['source'],row['target'])) for row in bank['entries']]
    file=INCOMING/'full-worker-fixtures.json';file.write_text(json.dumps(fixtures),encoding='utf8')
    raw=INCOMING/'full-worker-audit.raw.json'
    result=subprocess.run(['node','tests/check-transfers.mjs',str(file.relative_to(PROJECT)),str(raw.relative_to(PROJECT))],cwd=PROJECT,text=True,capture_output=True,timeout=7200)
    if result.returncode:raise ValueError('992-edge continuity audit failed: '+(result.stderr or result.stdout)[-2000:])
    report=json.loads(raw.read_text());report.update(passed=True,bank_sha256=signature,verified_at=time.time())
    common.atomic_json(proof,report);return True

def cycle(root,rejected,workers):
    local=transitions.catalog(5)
    seen={transitions.key(5,row['source'],row['target']):row.get('remote_sha256') for row in local['entries'] if row['status']=='ready'}
    snapshot=remote_snapshot(root,seen,rejected)
    status=dict(host='wqm',root=root,order=5,total=992,poses=32,workers=snapshot['metadata']['workers_total'],jobs=snapshot['jobs'],remote_ready=snapshot['remote_ready'],local_ready=local['ready'],updated_at=time.time(),phase='computing')
    with repository.disk_lock():
        rows=transitions.statuses()
        for remote in snapshot['entries']:
            row=rows[transitions.key(5,remote['source'],remote['target'])]
            if row['status']=='ready':continue
            row.update(status='validating' if remote['status']=='ready' else remote['status'],phase='本机物理与网页仿真复验' if remote['status']=='ready' else remote.get('phase','等待远端计算'),remote_status=remote['status'])
            for field in ('iterations','attempt','last_error'):
                if field in remote:row[field]=remote[field]
        transitions._write(rows)
    common.atomic_json(STATUS,status)
    common.INCOMING=INCOMING
    paths=common.pull_archive('wqm',root,snapshot)
    if paths:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(validate_candidate,path,row):row for path,row in paths}
            for future in as_completed(futures):
                row=futures[future];key=transitions.key(5,row['source'],row['target'])
                try:
                    print('IMPORTED '+json.dumps(future.result()),flush=True)
                    with repository.disk_lock():
                        rows=transitions.statuses();rows[key]['remote_sha256']=row['sha256'];transitions._write(rows)
                    rejected.pop(key,None)
                except Exception as error:
                    rejected[key]=row['sha256'];transitions.update(5,row['source'],row['target'],status='retry_pending',last_error=str(error)[-2000:],phase='复验未通过，保留候选等待细化')
                    print('REJECTED',key,str(error)[-1500:],flush=True)
                common.atomic_json(INCOMING/'rejections.json',rejected)
                status.update(local_ready=transitions.catalog(5)['ready'],updated_at=time.time());common.atomic_json(STATUS,status)
    if status['local_ready']==992:
        status['phase']='auditing_tour';common.atomic_json(STATUS,status)
        try:
            if full_audit():status['phase']='complete'
        except Exception as error:status.update(phase='tour_needs_review',last_error=str(error)[-2000:])
    elif not any(job['state'] in ('Q','R','E') for job in status['jobs']):status['phase']='needs_search'
    status['updated_at']=time.time();common.atomic_json(STATUS,status)
    print('SYNC '+json.dumps(status),flush=True)
    return status

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--watch',action='store_true');parser.add_argument('--interval',type=int,default=60);parser.add_argument('--local-workers',type=int,default=2);args=parser.parse_args()
    path=PurePosixPath(args.root)
    if not re.fullmatch(r'[A-Za-z0-9_./-]+',args.root) or '..' in path.parts or path.parent not in (PurePosixPath('/wangqm/hmy'),PurePosixPath('/data/wangqm/hmy')):parser.error('Workspace must be an immediate child of the authorized hmy directory')
    INCOMING.mkdir(parents=True,exist_ok=True);transitions.initialize()
    rejection_path=INCOMING/'rejections.json';rejected=json.loads(rejection_path.read_text()) if rejection_path.exists() else {}
    while True:
        try:status=cycle(args.root,rejected,max(1,min(4,args.local_workers)))
        except Exception as error:
            print('SYNC_ERROR',repr(error),flush=True)
            try:status=json.loads(STATUS.read_text(encoding='utf8'))
            except (OSError,ValueError):status={}
            status.update(phase='retry_sync',last_error=str(error)[-2000:],updated_at=time.time());common.atomic_json(STATUS,status)
        if not args.watch or status['phase'] in ('complete','tour_needs_review'):break
        time.sleep(max(30,args.interval))

if __name__=='__main__':main()
