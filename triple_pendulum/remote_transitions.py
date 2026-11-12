"""Pull fourth-order PBS results, independently validate, and publish locally.

The remote ready flag is never sufficient for admission. Both the local passive
Python plant and the exact browser Worker must successfully integrate each plan.
"""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib,json,re,subprocess,tarfile,time,uuid,shutil
from pathlib import Path,PurePosixPath
from . import transitions,repository

PROJECT=Path(__file__).resolve().parent.parent
RESULTS=PROJECT/'results'
INCOMING=RESULTS/'remote-n4'
REMOTE_STATUS=RESULTS/'fourth-order-remote.json'

def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    for attempt in range(40):
        try:temporary.replace(path);return
        except PermissionError:
            if attempt==39:raise
            time.sleep(.03)

def write_acceptance(status):
    bank=transitions.catalog(4);ready=[r for r in bank['entries'] if r['status']=='ready'];proofs=[r['verification'] for r in ready]
    report=dict(order=4,poses=16,total=240,ready=len(ready),direct=sum(not r.get('route_waypoints') for r in ready),via_equilibria=sum(bool(r.get('route_waypoints')) for r in ready),bank_sha256=transitions.bank_signature(),complete=bank['cruise_ready'].get(4,False),updated_at=time.time(),
        checks=['independent 1 ms passive-plant integration','exact page Worker integration','bounded cart force and force rate','no rail contact'],
        joint_control_actuators=0,cart_force_limit=120,force_rate_limit=500,rail_half_width=2.4,
        max_cart=max((r['max_cart'] for r in proofs),default=0.),max_force=max((r['max_force'] for r in proofs),default=0.),
        remote=status,entries=ready)
    atomic_json(RESULTS/'fourth-order-acceptance.json',report)

def remote_snapshot(host,root,seen):
    # Python source is sent on stdin, never interpolated into shell commands.
    code='ROOT='+repr(root)+'\nSEEN='+repr(seen)+'''\nimport json,re,subprocess,time,tarfile,uuid,sys,os
from pathlib import Path
root=Path(ROOT)
sys.path.insert(0,str(root))
os.environ['PENDULUM_CLUSTER_MODE']='1'
from triple_pendulum import transitions
metadata=json.loads((root/'job.json').read_text())
ids=metadata.get('job_ids',[metadata['job_id']])
r=subprocess.run(['timeout','10','/opt/tsce4/torque6/bin/qstat','-f']+ids,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True)
jobs=[]
for job_id in ids:
    block=next((b for b in r.stdout.split('Job Id:') if b.lstrip().startswith(job_id)), '')
    state=re.search(r'job_state = (\\w)',block)
    host=re.search(r'exec_host = ([^\\n]+)',block)
    jobs.append(dict(job_id=job_id,state=state.group(1) if state else 'unknown',node=host.group(1).split('/')[0] if host else None))
status_path=root/'equilibrium_transitions/status.json'
# A failed local replay invalidates that remote candidate, preserving the file
# for diagnosis. Active solver rounds will pick it up again on the next pass.
rejected={key:value for key,value in SEEN.items() if value!='*'}
transitions.initialize()
for key,digest in rejected.items():
    assert re.fullmatch('4-[UD]{4}-[UD]{4}',key)
    path=transitions.ROOT/'rejections'/(key+'.json');temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(dict(sha256=digest)));temporary.replace(path)
# This coordinator alone materializes the global index. Compute workers only
# publish per-case progress and immutable plan certificates.
rows=transitions.statuses();transitions._write(rows)
entries=[v for v in rows.values() if v['order']==4]
download=[]
for row in entries:
    key='4-'+row['source']+'-'+row['target']
    if row['status']=='ready' and SEEN.get(key) not in ('*',row['sha256']):download.append(row)
archive=None
if download:
    exports=root/'exports';exports.mkdir(exist_ok=True)
    archive=exports/('batch-'+uuid.uuid4().hex+'.tar.gz')
    with tarfile.open(str(archive),'w:gz') as tar:
        for row in download:tar.add(str(root/'equilibrium_transitions'/row['file']),arcname=row['file'])
print(json.dumps(dict(metadata=metadata,jobs=jobs,entries=entries,download=download,archive=str(archive) if archive else None,remote_ready=sum(v['status']=='ready' for v in entries))))
'''
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',host,root+'/venv/bin/python','-u','-'],input=code,cwd=PROJECT,text=True,encoding='utf8',capture_output=True,timeout=80)
    if result.returncode:raise RuntimeError(result.stderr[-1500:] or result.stdout[-1500:])
    return json.loads(result.stdout)

def resume_remaining(host,root):
    code='ROOT='+repr(root)+'''\nimport json,subprocess,time
from pathlib import Path
root=Path(ROOT);meta=json.loads((root/'job.json').read_text())
ids=meta.get('job_ids',[meta['job_id']])
r=subprocess.run(['timeout','10','/opt/tsce4/torque6/bin/qstat','-f']+ids,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True)
if any('job_state = '+state in r.stdout for state in ['Q','R','E']):print(json.dumps(dict(resumed=False,reason='active')));raise SystemExit()
rows=[v for v in json.loads((root/'equilibrium_transitions/status.json').read_text())['entries'].values() if v['order']==4]
ready=sum(row['status']=='ready' for row in rows);resumes=meta.get('resumes',0)
if resumes>=2 or ready<=meta.get('ready_at_last_resume',0):print(json.dumps(dict(resumed=False,reason='search_budget_or_no_progress')));raise SystemExit()
shards=meta.get('shards',1);pending=set()
for i,row in enumerate(sorted(rows,key=lambda r:'4-'+r['source']+'-'+r['target'])):
    if row['status']!='ready':pending.add(i%shards)
if not pending:print(json.dumps(dict(resumed=False,reason='all_ready')));raise SystemExit()
meta.setdefault('previous_job_ids',[]).extend(ids);jobs=[]
for index in sorted(pending):
    environment='PENDULUM_SHARD_INDEX='+str(index)+',PENDULUM_SHARDS='+str(shards)+',PENDULUM_START_ROUND='+str((resumes+1)*8)
    r=subprocess.run(['/opt/tsce4/torque6/bin/qsub','-N','pend4-r'+str(resumes+1)+'-'+str(index),'-o','pendulum4-pbs-r'+str(resumes+1)+'-'+str(index)+'.log','-v',environment,'fourth-order.pbs'],cwd=str(root),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True)
    if r.returncode:raise RuntimeError(r.stdout)
    jobs.append(dict(job_id=r.stdout.strip(),shard=index,submitted_at=time.time()))
    meta.update(jobs=jobs,job_ids=[j['job_id'] for j in jobs],job_id=jobs[0]['job_id'],resumes=resumes+1,ready_at_last_resume=ready)
    (root/'job.json').write_text(json.dumps(meta,indent=2))
print(json.dumps(dict(resumed=True,jobs=jobs,start_round=(resumes+1)*8,remote_ready=ready)))
'''
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',host,'python3','-u','-'],input=code,cwd=PROJECT,text=True,encoding='utf8',capture_output=True,timeout=100)
    if result.returncode:raise RuntimeError(result.stderr[-1200:] or result.stdout[-1200:])
    return json.loads(result.stdout)

def pull_archive(host,root,snapshot):
    path=snapshot['archive']
    if not path:return []
    if not path.startswith(root+'/exports/') or not re.fullmatch(r'[A-Za-z0-9_./-]+',path) or '..' in PurePosixPath(path).parts:raise ValueError('Unsafe remote archive path')
    destination=INCOMING/PurePosixPath(path).name;destination.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['scp','-q','-o','BatchMode=yes','-o','ConnectTimeout=15',host+':'+path,str(destination.relative_to(PROJECT))],cwd=PROJECT,check=True,capture_output=True,timeout=180)
    expected={r['file']:r for r in snapshot['download']};paths=[]
    with tarfile.open(destination) as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.name not in expected or len(PurePosixPath(member.name).parts)!=1 or member.size>20_000_000:raise ValueError('Unexpected remote archive member')
            encoded=archive.extractfile(member).read();row=expected[member.name]
            if hashlib.sha256(encoded).hexdigest()!=row['sha256']:raise ValueError('Remote transfer checksum mismatch')
            file=INCOMING/member.name;file.write_bytes(encoded);paths.append((str(file),row))
    if len(paths)!=len(expected):raise ValueError('Incomplete archive')
    return paths

def validate_and_admit(path,row,staging=None):
    if staging:
        transitions.ROOT=Path(staging)/'equilibrium_transitions';transitions._initialized_root=None
        repository.ROOT=Path(staging)/'trajectory_repository'
    from .model import Plant,Parameters
    from .control import analyze
    from .validate_plan import replay
    plan=json.loads(Path(path).read_text(encoding='utf8'));plant=Plant(Parameters(**plan['parameters']))
    if plant.n!=4 or plan.get('transition')!=dict(order=4,source=row['source'],target=row['target']):raise ValueError('Transition identity mismatch')
    report=replay(plant,plan,total=plan['duration']+15);history=report.pop('history')
    if not report['final_stable']:raise ValueError('Local nonlinear replay did not settle')
    if not plan.get('route_waypoints'):
        from .direct_quality import intermediate_hold
        quality=intermediate_hold(plant,history[:,1:-1],.02,row['source'],row['target'])
        if not quality['passed']:raise ValueError('Direct candidate stops at an intermediate equilibrium: '+str(quality))
        plan['direct_quality']=quality
    prefix=INCOMING/(transitions.key(4,row['source'],row['target'])+'-'+row['sha256'][:12])
    fixture=prefix.with_suffix('.fixture.json');worker_report=prefix.with_suffix('.worker.json')
    fixture.write_text(json.dumps([dict(design=analyze(plant,target=repository.angles(row['target'])),source_design=analyze(plant,target=repository.angles(row['source'])),plan=plan)]),encoding='utf8')
    result=subprocess.run(['node','tests/check-transfers.mjs',str(fixture.relative_to(PROJECT)),str(worker_report.relative_to(PROJECT))],cwd=PROJECT,text=True,capture_output=True,timeout=150)
    if result.returncode:raise ValueError('Actual Worker rejected the plan: '+(result.stderr or result.stdout)[-1200:])
    plan['worker_verification']=json.loads(worker_report.read_text())
    plan['remote_provenance']=dict(host=row.get('origin_host','wqm'),sha256=row['sha256'])
    if not transitions.admit(plant,row['source'],row['target'],plan,report,history):raise ValueError('Local actuator/rail/rate/tracking limits failed')
    return dict(source=row['source'],target=row['target'],duration=plan['duration'],max_cart=report['max_cart'],max_force=report['max_force'])

def validate_reversal(row):
    from .model import Plant,Parameters
    from .precompute_equilibria import reverse_reference
    from .planner import tracking_gains
    plant=Plant(Parameters(**row['parameters']));source,target=row['target'],row['source']
    original=transitions.lookup(plant,row['source'],row['target'])
    plan=reverse_reference(plant,original,source,target)
    plan.update(transition=dict(order=4,source=source,target=target),parameters=plant.p.dict(),force_rate=500.,strict_rest=True)
    plan['gains']=tracking_gains(plant,plan)
    encoded=json.dumps(plan).encode('utf8');path=INCOMING/('reversed-'+transitions.key(4,source,target)+'.json');path.write_bytes(encoded)
    candidate=dict(source=source,target=target,sha256=hashlib.sha256(encoded).hexdigest(),origin_host='verified-reference-reversal')
    return validate_and_admit(str(path),candidate)

def publish_verified(host,root,remote_rows):
    """Share independently certified local results so PBS skips duplicate work."""
    remote={transitions.key(4,r['source'],r['target']):r for r in remote_rows}
    rows=[r for r in transitions.catalog(4)['entries'] if r['status']=='ready' and not r.get('route_waypoints') and remote[transitions.key(4,r['source'],r['target'])]['status']!='ready']
    if not rows:return
    bundle=INCOMING/('verified-'+uuid.uuid4().hex+'.tar.gz')
    manifest=INCOMING/'publish-manifest.json';manifest.write_text(json.dumps(rows),encoding='utf8')
    with tarfile.open(bundle,'w:gz') as archive:
        archive.add(manifest,arcname='manifest.json')
        for row in rows:archive.add(transitions.ROOT/row['file'],arcname=row['file'])
    remote_path=root+'/'+bundle.name
    subprocess.run(['scp','-q','-o','BatchMode=yes','-o','ConnectTimeout=15',str(bundle.relative_to(PROJECT)),host+':'+remote_path],cwd=PROJECT,check=True,capture_output=True,timeout=120)
    code='ROOT='+repr(root)+'\nBUNDLE='+repr(remote_path)+'''\nimport json,tarfile,hashlib,time,sys,uuid,os
from pathlib import Path
root=Path(ROOT);status=root/'equilibrium_transitions/status.json'
sys.path.insert(0,str(root))
os.environ['PENDULUM_CLUSTER_MODE']='1'
from triple_pendulum import transitions
transitions.initialize();rows=transitions.statuses()
with tarfile.open(BUNDLE) as archive:
    offered=json.load(archive.extractfile('manifest.json'));accepted=0
    if offered:
        for row in offered:
            key='4-'+row['source']+'-'+row['target']
            if rows[key]['status']=='ready':continue
            assert row['order']==4 and row['file'] in (key+'.json',key+'-'+row['sha256'][:16]+'.json')
            encoded=archive.extractfile(row['file']).read();assert hashlib.sha256(encoded).hexdigest()==row['sha256']
            plan=json.loads(encoded);proof=plan['verification'];worker=plan['worker_verification']
            assert plan['transition']==dict(order=4,source=row['source'],target=row['target'])
            assert proof['final_stable'] and proof['max_cart']<.96*row['parameters']['rail'] and proof['max_force']<=row['parameters']['max_force'] and proof['max_force_rate']<=500.000001
            assert len(worker['individual'])==1 and worker['rail_contacts']==0 and worker['live_planner_requests']==0
            row['file']=key+'-'+row['sha256'][:16]+'.json'
            file=transitions.ROOT/row['file'];temporary=file.with_name(file.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(encoded);temporary.replace(file)
            row.update(phase='独立本机与页面 Worker 复验通过，分布式共享',updated_at=time.time(),shared_local_validation=True)
            certificate=transitions.ROOT/'certificates'/(key+'.json');temporary=certificate.with_name(certificate.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(row,ensure_ascii=False));temporary.replace(certificate);accepted+=1
print(json.dumps(dict(shared_verified=accepted)))
'''
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15',host,root+'/venv/bin/python','-u','-'],input=code,cwd=PROJECT,text=True,encoding='utf8',capture_output=True,timeout=80)
    if result.returncode:raise RuntimeError(result.stderr[-1500:])
    print('SHARED '+result.stdout.strip(),flush=True)

def merge_progress(entries):
    with repository.disk_lock():
        rows=transitions.statuses()
        for remote in entries:
            row=rows[transitions.key(4,remote['source'],remote['target'])]
            if row['status']=='ready':continue
            status='validating' if remote['status']=='ready' else remote['status']
            row.update(status=status,remote_status=remote['status'],phase='本机物理与页面 Worker 复验' if status=='validating' else remote.get('phase','等待远程计算'))
            for field in ('iterations','attempt','last_error'):
                if field in remote:row[field]=remote[field]
        transitions._write(rows)

def full_worker_audit(output_directory=None):
    from .model import Plant,Parameters
    from .control import analyze
    rows=transitions.catalog(4)['entries']
    if any(r['status']!='ready' for r in rows):return False
    output=Path(output_directory) if output_directory else RESULTS;output.mkdir(parents=True,exist_ok=True)
    signature=transitions.bank_signature();audit_path=output/'fourth-order-worker-audit.json'
    if audit_path.exists():
        prior=json.loads(audit_path.read_text())
        if prior.get('passed') and prior.get('bank_sha256')==signature:return True
    plant=Plant(Parameters(n=4));designs={code:analyze(plant,target=repository.angles(code)) for code in transitions.patterns(4)}
    fixtures=[dict(design=designs[r['target']],source_design=designs[r['source']],plan=transitions.lookup(plant,r['source'],r['target'])) for r in rows]
    fixture=output/'fourth-order-worker-fixtures.json';fixture.write_text(json.dumps(fixtures),encoding='utf8')
    raw_path=output/'fourth-order-worker-audit.raw.json'
    result=subprocess.run(['node','tests/check-transfers.mjs',str(fixture.relative_to(PROJECT)),str(raw_path.relative_to(PROJECT))],cwd=PROJECT,text=True,capture_output=True,timeout=1800)
    if result.returncode:raise ValueError('Full fourth-order continuous tour failed: '+result.stderr[-1800:])
    report=json.loads(raw_path.read_text());report.update(passed=True,bank_sha256=signature,verified_at=time.time());atomic_json(audit_path,report)
    print('FOURTH_ORDER_FULL_AUDIT_PASS 240 individual + 240 continuous',flush=True);return True

def prepare_upgrade():
    batch=RESULTS/'fourth-order-upgrades'/uuid.uuid4().hex;bank=batch/'equilibrium_transitions';bank.mkdir(parents=True)
    rows=transitions.statuses()
    for row in rows.values():
        if row['status']=='ready':shutil.copy2(transitions.ROOT/row['file'],bank/row['file'])
    atomic_json(bank/'status.json',dict(schema=2,entries=rows))
    signature=transitions.bank_signature(list(rows.values()));atomic_json(batch/'baseline.json',dict(bank_sha256=signature))
    try:
        proof=json.loads((RESULTS/'fourth-order-worker-audit.json').read_text(encoding='utf8'))
        if proof.get('passed') and proof.get('bank_sha256')==signature:atomic_json(RESULTS/'fourth-order-worker-audits'/(signature+'.json'),proof)
    except (OSError,ValueError):pass
    return str(batch)

def audit_and_promote(staging):
    batch=Path(staging);live_bank=transitions.ROOT;live_repo=repository.ROOT
    try:
        transitions.ROOT=batch/'equilibrium_transitions';transitions._initialized_root=None;repository.ROOT=batch/'trajectory_repository'
        if not full_worker_audit(batch/'results'):raise ValueError('Staged bank is incomplete')
        proposed=transitions.statuses();replays=repository.catalog()
    finally:transitions.ROOT=live_bank;transitions._initialized_root=None;repository.ROOT=live_repo
    proof=json.loads((batch/'results/fourth-order-worker-audit.json').read_text(encoding='utf8'))
    baseline=json.loads((batch/'baseline.json').read_text(encoding='utf8'))['bank_sha256']
    if transitions.bank_signature()!=baseline:raise ValueError('Live bank changed during staged verification')
    for meta in replays:
        data=json.loads((batch/'trajectory_repository'/(meta['id']+'.json')).read_text(encoding='utf8'));repository._write(meta,data)
    with repository.disk_lock():
        rows=transitions.statuses();changed=0
        if transitions.bank_signature(list(rows.values()))!=baseline:raise ValueError('Concurrent bank update')
        for key,row in proposed.items():
            if row['order']!=4 or row.get('sha256')==rows[key].get('sha256'):continue
            encoded=(batch/'equilibrium_transitions'/row['file']).read_bytes()
            if hashlib.sha256(encoded).hexdigest()!=row['sha256']:raise ValueError('Staged digest changed')
            row=dict(row,file=key+'-'+row['sha256'][:16]+'.json')
            temporary=live_bank/(row['file']+'.'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(encoded);temporary.replace(live_bank/row['file']);rows[key]=row;changed+=1
        if transitions.bank_signature(list(rows.values()))!=proof['bank_sha256']:raise ValueError('Staged audit does not match proposed publication')
        # Both old and new bank certificates are available before publishing the
        # new index. A reader can use either snapshot without losing tour access.
        registry=RESULTS/'fourth-order-worker-audits';atomic_json(registry/(proof['bank_sha256']+'.json'),proof)
        transitions._write(rows);atomic_json(RESULTS/'fourth-order-worker-audit.json',proof)
    print('PROMOTED_DIRECT',changed,'without interrupting the active bank',flush=True)
    return changed

def cycle(args,rejected):
    local=transitions.catalog(4);seen={transitions.key(4,r['source'],r['target']):'*' for r in local['entries'] if r['status']=='ready' and not r.get('route_waypoints')};seen.update({key:value for key,value in rejected.items() if key not in seen})
    snapshot=remote_snapshot(args.host,args.root,seen);merge_progress(snapshot['entries'])
    status=dict(host=args.host,root=args.root,jobs=snapshot['jobs'],workers=24,total=240,remote_ready=snapshot['remote_ready'],local_ready=local['ready'],updated_at=time.time(),phase='computing')
    atomic_json(REMOTE_STATUS,status)
    paths=pull_archive(args.host,args.root,snapshot)
    if paths:
        staging=prepare_upgrade() if local['ready']==240 else None;staged_success=0
        with ProcessPoolExecutor(max_workers=args.local_workers) as pool:
            futures={pool.submit(validate_and_admit,path,row,staging):row for path,row in paths}
            for future in as_completed(futures):
                row=futures[future];key=transitions.key(4,row['source'],row['target'])
                try:
                    outcome=future.result();staged_success+=1;print(('STAGED ' if staging else 'IMPORTED ')+json.dumps(outcome),flush=True)
                    if key in rejected:rejected.pop(key);atomic_json(RESULTS/'fourth-order-import-rejections.json',rejected)
                except Exception as error:
                    rejected[key]=row['sha256'];atomic_json(RESULTS/'fourth-order-import-rejections.json',rejected)
                    transitions.update(4,row['source'],row['target'],status='retry_pending',last_error=str(error)[-1800:],phase='本机验收未通过，保留候选等待重算')
                    print('REJECTED',key,str(error)[-1200:],flush=True)
                status['local_ready']=transitions.catalog(4)['ready'];status['updated_at']=time.time();atomic_json(REMOTE_STATUS,status)
        if staging and staged_success:
            status['phase']='auditing_upgrade';atomic_json(REMOTE_STATUS,status)
            try:audit_and_promote(staging)
            except Exception as error:
                status.update(phase='refining_direct',upgrade_error=str(error)[-2000:]);print('UPGRADE_RETAINED_CURRENT_BANK',repr(error),flush=True)
    # Reverse references are only candidates: passive damping is not reversed.
    # Every candidate still passes fresh Python AND exact Worker integrations.
    reversal_path=RESULTS/'fourth-order-reversal-attempts.json'
    attempts=json.loads(reversal_path.read_text()) if reversal_path.exists() else {}
    rows=transitions.statuses();candidates=[]
    for row in list(rows.values()):
        if row['order']!=4 or row['status']!='ready':continue
        reverse_key=transitions.key(4,row['target'],row['source'])
        if rows[reverse_key]['status']=='ready' or attempts.get(reverse_key)==row['sha256']:continue
        attempts[reverse_key]=row['sha256'];candidates.append(row)
    if candidates:
        atomic_json(reversal_path,attempts)
        with ProcessPoolExecutor(max_workers=args.local_workers) as pool:
            futures={pool.submit(validate_reversal,row):row for row in candidates}
            for future in as_completed(futures):
                row=futures[future]
                try:print('REVERSED_READY '+json.dumps(future.result()),flush=True)
                except Exception as error:print('REVERSE_NEEDS_NLP',row['target'],row['source'],str(error)[-300:],flush=True)
                status['local_ready']=transitions.catalog(4)['ready'];status['updated_at']=time.time();atomic_json(REMOTE_STATUS,status)
    publish_verified(args.host,args.root,snapshot['entries'])
    status['local_ready']=transitions.catalog(4)['ready'];status['updated_at']=time.time()
    if status['local_ready']==240:
        status['phase']='auditing_tour';atomic_json(REMOTE_STATUS,status)
        try:
            if full_worker_audit():status['phase']='refining_direct' if any(r.get('route_waypoints') for r in transitions.catalog(4)['entries']) else 'complete'
        except Exception as error:
            status.update(phase='tour_needs_review',audit_error=str(error)[-2000:])
    elif not any(job['state'] in ('Q','R','E') for job in status['jobs']):
        resumed=resume_remaining(args.host,args.root);print('RESUME '+json.dumps(resumed),flush=True)
        status['phase']='resubmitted' if resumed.get('resumed') or resumed.get('reason')=='active' else 'needs_search'
    if status['phase']=='refining_direct' and not any(job['state'] in ('Q','R','E') for job in status['jobs']):
        resumed=resume_remaining(args.host,args.root);print('RESUME_DIRECT '+json.dumps(resumed),flush=True)
        if not(resumed.get('resumed') or resumed.get('reason')=='active'):status['phase']='complete_with_routes'
    status['updated_at']=time.time();atomic_json(REMOTE_STATUS,status);write_acceptance(status);print('SYNC '+json.dumps(status),flush=True)
    return status

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='wqm');parser.add_argument('--root',default='/data/wangqm/hmy/pendulum4_20261112')
    parser.add_argument('--watch',action='store_true');parser.add_argument('--interval',type=int,default=30);parser.add_argument('--local-workers',type=int,default=2);args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',args.host):parser.error('Invalid SSH host')
    if not args.root.startswith('/data/wangqm/hmy/') or '..' in PurePosixPath(args.root).parts:parser.error('Remote workspace must be inside the authorized hmy directory')
    args.local_workers=max(1,min(4,args.local_workers));transitions.initialize();INCOMING.mkdir(parents=True,exist_ok=True)
    rejection_path=RESULTS/'fourth-order-import-rejections.json';rejected=json.loads(rejection_path.read_text()) if rejection_path.exists() else {}
    while True:
        try:status=cycle(args,rejected)
        except Exception as error:
            print('SYNC_ERROR',repr(error),flush=True)
            try:status=json.loads(REMOTE_STATUS.read_text(encoding='utf8'))
            except (OSError,ValueError):status={}
            status.update(phase='retry_sync',last_error=str(error)[-1200:],updated_at=time.time());atomic_json(REMOTE_STATUS,status)
        if not args.watch or status['phase'] in ('complete','complete_with_routes'):break
        if status['phase'] in ('needs_search','tour_needs_review'):raise SystemExit(2)
        time.sleep(max(15,args.interval))

if __name__=='__main__':main()
