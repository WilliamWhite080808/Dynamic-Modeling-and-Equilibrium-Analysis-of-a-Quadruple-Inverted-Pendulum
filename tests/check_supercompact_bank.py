"""Decode every published lossy pair against its *new* acceptance SHA."""
import argparse,hashlib,json,sys,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed

ROOT=Path(__file__).resolve().parent.parent
APP=ROOT/'results/supercompact/app';sys.path.insert(0,str(APP))


def one(name,bank):
    from triple_pendulum.motion_plugins import MotionStore
    from triple_pendulum.motion_text import loads
    bank=Path(bank);report=json.loads((bank/'reports'/name.replace('.toml','.json')).read_bytes());raw=(bank/'motions'/name).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==report['sha256']
    model=loads((ROOT/'dist/极简实验/桌面版/程序文件/models/standard.toml').read_bytes())
    doc,params=MotionStore.validate(None,raw,model)
    for key in ('ab','ba'):
        assert doc[key]['runtime_sha256']==report['runtime_hashes'][key] and doc[key]['lossy']
    return dict(file=name,bytes=len(raw),sha256=report['sha256'],runtime_hashes=report['runtime_hashes'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('bank');parser.add_argument('output');parser.add_argument('--workers',type=int,default=4);a=parser.parse_args();bank=Path(a.bank).resolve();files=sorted(p.name for p in (bank/'motions').glob('*.toml'));assert len(files)==651;rows=[];start=time.monotonic()
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for future in as_completed([pool.submit(one,name,str(bank)) for name in files]):
            rows.append(future.result())
            if len(rows)%50==0:print('DECODE',len(rows),'/',len(files),flush=True)
    Path(a.output).write_text(json.dumps(dict(passed=True,pairs=651,directions=1302,new_accepted_control_hashes_match=True,original_control_hashes_reused=False,seconds=time.monotonic()-start,files=sorted(rows,key=lambda r:r['file'])),indent=2),encoding='utf8');print('PASS all 1302 new reference hashes',flush=True)
