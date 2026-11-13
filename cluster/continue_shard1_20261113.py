"""One checkpoint-preserving continuation; refuses a changed or live job."""
from pathlib import Path
import json, subprocess, time

root = Path('/data/wangqm/hmy/pendulum5_20261112')
assert root.resolve() == root and root.parent == Path('/data/wangqm/hmy')
metadata = root/'job.json'
job = json.loads(metadata.read_text())
old = next(x for x in job['jobs'] if x['shard'] == 1)
assert old['job_id'] == '1128867.mu01', 'Metadata changed; inspect before resubmitting'
status = subprocess.run(['/opt/tsce4/torque6/bin/qstat', '-f', old['job_id']], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
assert status.returncode != 0 and 'Unknown Job Id' in status.stderr, 'Previous job may still exist'
log = (root/'solver-1.log').read_text(errors='replace')
assert log.rstrip().endswith('RESULT 115 / 124'), 'Previous result changed; inspect first'
stamp = int(time.time())
(root/f'job-before-shard1-continuation5-{stamp}.json').write_bytes(metadata.read_bytes())
newid = subprocess.check_output([
    '/opt/tsce4/torque6/bin/qsub', '-N', 'pend5-r1c5',
    '-l', 'nodes=cu31:ppn=8,walltime=08:00:00',
    '-o', str(root/'pbs-1-continuation5.log'), '-d', str(root),
    '-v', 'PENDULUM_SHARD_INDEX=1,PENDULUM_SHARDS=8,PENDULUM_START_ROUND=13,TMPDIR='+str(root/'tmp'),
    str(root/'fifth-order-traced.pbs')], cwd=str(root), universal_newlines=True).strip()
assert newid.endswith('.mu01'), newid
job.setdefault('retired_jobs', []).append(dict(old, retired_at=time.time(), reason='Completed four rounds; RESULT 115/124; preserve nine remaining case checkpoints'))
replacement = dict(job_id=newid, shard=1, submitted_at=time.time(), start_round=13, rounds=4,
                   requested_node='cu31', continuation=5, pending_at_submission=9,
                   startup_trace=True, case_status_io=True, reason='Continue completed rounds with checkpoints; Maui offers 28 processors for over 24 hours')
job['jobs'] = [replacement if x['shard'] == 1 else x for x in job['jobs']]
job['job_ids'] = [x['job_id'] for x in job['jobs']]
temporary = metadata.with_suffix('.new')
temporary.write_text(json.dumps(job, indent=2))
temporary.replace(metadata)
print(json.dumps(replacement), flush=True)
