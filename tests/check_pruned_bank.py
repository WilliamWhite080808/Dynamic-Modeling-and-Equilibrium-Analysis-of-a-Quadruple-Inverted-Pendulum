"""Every v4 pair must decode to the original certified runtime SHA."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed

def one(path):
    from triple_pendulum.motion_text import read_motion,loads
    from triple_pendulum.motion_plugins import MotionStore
    path=Path(path);root=path.parent.parent;model=loads((root/'models/standard.toml').read_bytes())
    doc,params=MotionStore.validate(None,path.read_bytes(),model)
    return dict(file=path.name,n=doc['n'],directions={k:doc[k]['runtime_sha256'] for k in ('ab','ba')},sha256=hashlib.sha256(path.read_bytes()).hexdigest())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('app');p.add_argument('output');p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    app=Path(a.app).resolve();sys.path.insert(0,str(app));files=sorted((app/'motions').glob('*.toml'));rows=[];started=time.monotonic()
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for future in as_completed([pool.submit(one,str(file)) for file in files]):
            rows.append(future.result())
            if len(rows)%50==0:print('EXACT',len(rows),'/',len(files),flush=True)
    index=json.loads((app/'.cache/trajectory-index.json').read_bytes());assert len(rows)==len(index['files'])==651
    for row in rows:
        meta=index['files'][row['file']];assert row['sha256']==meta['sha256']
        assert all(row['directions'][k]==meta['directions'][k]['runtime_sha256'] for k in ('ab','ba'))
    report=dict(passed=True,pairs=len(rows),directions=2*len(rows),original_hashes_unchanged=True,seconds=time.monotonic()-started,files=sorted(rows,key=lambda r:r['file']))
    Path(a.output).write_text(json.dumps(report,indent=2),encoding='utf8');print({k:v for k,v in report.items() if k!='files'},flush=True)
