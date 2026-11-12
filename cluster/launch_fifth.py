"""Deploy a resumable 992-edge calculation into an explicitly authorized hmy root."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time

PROJECT=Path(__file__).resolve().parent.parent

def run_remote(code):
    completed=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','wqm','python3','-u','-'],input=code,text=True,encoding='utf8',capture_output=True,timeout=150)
    if completed.returncode:raise RuntimeError(completed.stderr+'\n'+completed.stdout)
    return json.loads(completed.stdout)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',required=True,choices=['/wangqm/hmy','/data/wangqm/hmy'])
    parser.add_argument('--name',default='pendulum5_20261112')
    parser.add_argument('--shards',type=int,default=8)
    args=parser.parse_args()
    if not args.name.startswith('pendulum5_') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in args.name):parser.error('Invalid workspace name')
    if not 1<=args.shards<=8:parser.error('Use 1..8 shards')
    root=str(PurePosixPath(args.base)/args.name)
    incoming=PROJECT/'results/remote-n5';incoming.mkdir(parents=True,exist_ok=True)
    bundle=incoming/'source.tar.gz'
    with tarfile.open(bundle,'w:gz') as archive:
        for file in sorted((PROJECT/'triple_pendulum').glob('*.py')):archive.add(file,arcname=file.relative_to(PROJECT).as_posix())
        archive.add(PROJECT/'cluster/fifth-order.pbs',arcname='fifth-order.pbs')
        status=json.loads((PROJECT/'precomputed_swingups/status.json').read_text(encoding='utf8'))
        status['entries']={key:row for key,row in status['entries'].items() if row['order']==5}
        for row in status['entries'].values():
            if row['status']=='ready':archive.add(PROJECT/'precomputed_swingups'/row['file'],arcname='precomputed_swingups/'+row['file'])
        encoded=json.dumps(status).encode();info=tarfile.TarInfo('precomputed_swingups/status.json');info.size=len(encoded);archive.addfile(info,io.BytesIO(encoded))
    digest=hashlib.sha256(bundle.read_bytes()).hexdigest()
    metadata=run_remote('ROOT='+repr(root)+'\nBASE='+repr(args.base)+'''\nfrom pathlib import Path
import json
base=Path(BASE);assert base.is_dir() and base.resolve()==base
root=Path(ROOT);assert root.parent==base
root.mkdir(exist_ok=True)
assert root.resolve().parent==base
assert not (root/'job.json').exists(), 'Workspace already submitted; inspect it instead of duplicating jobs'
for name in ['tmp','cache','exports','results','trajectory_repository']: (root/name).mkdir(exist_ok=True)
print(json.dumps(dict(root=str(root),prepared=True)))
''')
    subprocess.run(['scp','-q','-o','BatchMode=yes','-o','ConnectTimeout=15',str(bundle),'wqm:'+root+'/source.tar.gz'],check=True,timeout=150)
    report=run_remote('ROOT='+repr(root)+'\nDIGEST='+repr(digest)+'\nSHARDS='+repr(args.shards)+'''\nimport os,json,sys,hashlib,subprocess,tarfile,time
from pathlib import Path
root=Path(ROOT);assert root.resolve()==root
os.chdir(root)
os.environ.update(TMPDIR=str(root/'tmp'),TMP=str(root/'tmp'),TEMP=str(root/'tmp'),XDG_CACHE_HOME=str(root/'cache'),PYTHONDONTWRITEBYTECODE='1',PYTHONPYCACHEPREFIX=str(root/'cache/pycache'))
assert hashlib.sha256((root/'source.tar.gz').read_bytes()).hexdigest()==DIGEST
with tarfile.open(str(root/'source.tar.gz')) as archive:
    for member in archive.getmembers():
        path=root/member.name
        assert member.isfile() and str(path.resolve()).startswith(str(root)+'/')
    archive.extractall(str(root))
old=root.parent/'pendulum4_20261112/venv'
assert old.is_dir()
if not (root/'venv').exists():subprocess.run(['cp','-a',str(old),str(root/'venv')],check=True)
python=str(root/'venv/bin/python')
env=dict(os.environ,PENDULUM_CLUSTER_MODE='0',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',OMP_NUM_THREADS='1')
subprocess.run([python,'-c','from triple_pendulum import transitions; transitions.initialize(); assert transitions.catalog(5)["total"]==992'],cwd=str(root),env=env,check=True)
pbs=root/'fifth-order.pbs';pbs.write_bytes(pbs.read_bytes().replace(b'\\r\\n',b'\\n'))
meta=dict(order=5,poses=32,total=992,root=str(root),submitted_at=time.time(),shards=SHARDS,workers_per_job=8,workers_total=8*SHARDS,source_sha256=DIGEST,jobs=[],job_ids=[],queue='medium',joint_control_actuators=0,cart_force_limit=120,force_rate_limit=500,rail_half_width=2.4)
for shard in range(SHARDS):
    output=str(root/('pbs-'+str(shard)+'.log'))
    environment='PENDULUM_SHARD_INDEX='+str(shard)+',PENDULUM_SHARDS='+str(SHARDS)+',TMPDIR='+str(root/'tmp')
    result=subprocess.run(['/opt/tsce4/torque6/bin/qsub','-N','pend5-'+str(shard),'-o',output,'-d',str(root),'-v',environment,str(pbs)],cwd=str(root),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True)
    if result.returncode:raise RuntimeError(result.stdout)
    job=dict(job_id=result.stdout.strip(),shard=shard,submitted_at=time.time());meta['jobs'].append(job);meta['job_ids'].append(job['job_id']);meta['job_id']=meta['job_ids'][0]
    temporary=root/'job.tmp';temporary.write_text(json.dumps(meta,indent=2));temporary.replace(root/'job.json')
print(json.dumps(meta))
''')
    (incoming/'launch.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
