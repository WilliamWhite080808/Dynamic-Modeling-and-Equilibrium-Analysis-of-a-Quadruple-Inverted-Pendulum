"""Remote-only checkpoint continuation, no duplicate jobs, <=150 cores."""
from pathlib import Path
import argparse,json,subprocess,time,re

root=Path('/data/wangqm/hmy/pendulum5_20261112')
assert root.resolve()==root and root.parent==Path('/data/wangqm/hmy')
qstat='/opt/tsce4/torque6/bin/qstat'
qsub='/opt/tsce4/torque6/bin/qsub'
parser=argparse.ArgumentParser();parser.add_argument('--only-shards');args=parser.parse_args()
selected=set(map(int,args.only_shards.split(','))) if args.only_shards is not None else None
assert selected is None or selected and selected.issubset(set(range(8))),'Invalid shard selection'
path=root/'job.json';job=json.loads(path.read_text());live=set()
assert job.get('mode') not in ('four-method-portfolio','portfolio-preparing'),'Portfolio uses portfolio_admin.py, not legacy shard continuation'
for old in job['jobs']:
    p=subprocess.run([qstat,'-f',old['job_id']],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
    if p.returncode:
        assert 'Unknown Job Id' in p.stderr,'Cannot establish previous job state'
    else:live.add(old['shard'])
assert not live if selected is None else not live.intersection(selected),'A selected previous job still exists; inspect instead of duplicating'
allrows=json.loads((root/'equilibrium_transitions/status.json').read_text())['entries']
keys=sorted(k for k,r in allrows.items() if r['order']==5)
assert len(keys)==992
nodes={0:'cu14',1:'cu31',2:'cu15',3:'cu16',4:'cu19',5:'cu30',6:'cu20',7:'cu15'}
stamp=int(time.time());(root/('job-before-tail-'+str(stamp)+'.json')).write_bytes(path.read_bytes())
def save_job():
    job['job_ids']=[x['job_id'] for x in job['jobs']]
    job['workers_total']=sum(x.get('workers',8) for x in job['jobs']);job['core_limit']=150
    temporary=path.with_suffix('.new');temporary.write_text(json.dumps(job,indent=2));temporary.replace(path)
allocations=[]
for old in job['jobs']:
    if selected is not None and old['shard'] not in selected:continue
    shard=old['shard'];pending=[]
    for k in keys[shard::8]:
        certificate=root/'equilibrium_transitions/certificates'/(k+'.json')
        try:c=json.loads(certificate.read_text())
        except (OSError,ValueError):c={}
        try:r=json.loads((root/'equilibrium_transitions/rejections'/(k+'.json')).read_text())
        except (OSError,ValueError):r={}
        if c.get('status')!='ready' or r.get('sha256')==c.get('sha256'):pending.append(k)
    if not pending:
        if not old.get('completed'):
            job.setdefault('retired_jobs',[]).append(dict(old,retired_at=time.time(),reason='All shard directions certified; no replacement job needed'))
            finished=dict(old,workers=0,completed=True,completed_at=time.time())
            job['jobs']=[finished if x['shard']==shard else x for x in job['jobs']]
            save_job();print(json.dumps(dict(shard=shard,completed=True,workers=0)),flush=True)
        continue
    cpus=min(8 if shard in (1,6) else 16,len(pending))
    log=(root/('solver-'+str(shard)+'.log')).read_text(errors='replace')
    completed=bool(re.search(r'RESULT \d+ / 124\s*$',log))
    rounds=re.findall(r'ROUND (\d+) pending',log)
    assert rounds,'No round checkpoint marker for shard '+str(shard)
    start=old.get('start_round',0)+old.get('rounds',4) if completed else max(old.get('start_round',0),int(rounds[-1])-1)
    allocations.append((old,shard,pending,cpus,start,completed))
assert sum(x.get('workers',8) for x in job['jobs'] if x['shard'] in live)+sum(x[3] for x in allocations)<=150
for old,shard,pending,cpus,start,completed in allocations:
    check=subprocess.run([qstat,'-f',old['job_id']],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
    assert check.returncode and 'Unknown Job Id' in check.stderr,'Selected previous job must remain absent before submission'
    ident=subprocess.check_output([qsub,'-N','pend5-tail-'+str(shard),'-l','nodes='+nodes[shard]+':ppn='+str(cpus)+',mem='+('64gb' if cpus>8 else '32gb')+',walltime=08:00:00',
        '-o',str(root/('pbs-tail-'+str(shard)+'-'+str(stamp)+'.log')),'-d',str(root),
        '-v','PENDULUM_SHARD_INDEX='+str(shard)+',PENDULUM_SHARDS=8,PENDULUM_START_ROUND='+str(start)+',PENDULUM_WORKERS='+str(cpus)+',TMPDIR='+str(root/'tmp'),str(root/'fifth-order-tail.pbs')],cwd=str(root),universal_newlines=True).strip()
    assert ident.endswith('.mu01'),ident
    replacement=dict(job_id=ident,shard=shard,submitted_at=time.time(),start_round=start,rounds=4,requested_node=nodes[shard],workers=cpus,pending_at_submission=len(pending),checkpoint_preserved=True)
    job.setdefault('retired_jobs',[]).append(dict(old,retired_at=time.time(),reason='Completed round result; continue remaining cases' if completed else 'Old job absent from PBS before RESULT; resume incomplete round and preserve all checkpoints'))
    job['jobs']=[replacement if x['shard']==shard else x for x in job['jobs']]
    save_job()
    print(json.dumps(replacement),flush=True)
