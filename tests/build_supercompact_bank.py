"""Bounded-lossy candidates: actual independent physical and Worker admission.

Run using the isolated, pinned recipient interpreter. Original bank untouched.
"""
import argparse,hashlib,json,os,subprocess,sys,time,gzip
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed

ROOT=Path(__file__).resolve().parent.parent
APP=ROOT/'results/supercompact/app'
sys.path.insert(0,str(APP))
import triple_pendulum
triple_pendulum.__path__.append(str(ROOT/'triple_pendulum'))
OUT=Path(os.environ.get('PENDULUM_LOSSY_BANK',str(ROOT/'results/supercompact/bank-final')))


def one(name):
    import numpy as np
    from triple_pendulum.motion_text import loads
    from triple_pendulum.motion_lossy import encode_additive,reconstruct,motion_bytes,acceptance_token
    from triple_pendulum.motion_plugins import digest,runtime
    from triple_pendulum.model import Plant,Parameters
    from triple_pendulum.control import analyze
    from triple_pendulum.validate_plan import replay
    from triple_pendulum.direct_quality import intermediate_hold
    file=ROOT/'dist/极简实验/桌面版/程序文件/motions'/name;raw=file.read_bytes();header=loads(raw);n=header['n'];ends=header['ends']
    complete=OUT/'reports'/name.replace('.toml','.json')
    if complete.exists():return json.loads(complete.read_bytes())
    manifest=json.loads((ROOT/'results/certified-bank-manifest.json').read_bytes())['rows']
    originals=[]
    for a,b in (ends,ends[::-1]):
        row=next(r for r in manifest if (r['order'],r['source'],r['target'])==(n,a,b));path=ROOT/'equilibrium_transitions'/row['file']
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Original certification SHA changed')
        originals.append(json.loads(data))
    budget=int(len(raw)*(.25 if n<=2 else .1));budget=max(budget,3000) if n<=2 else budget
    trials=[];specs=[('a',level,order) for level in range(6) for order in (2,1,0,3,4)]
    plant=Plant(Parameters(n=n));designs={s:analyze(plant,target=[0. if c=='U' else float(np.pi) for c in s]) for s in ends}
    for kind,a,b in specs:
        directions={key:encode_additive(p,a,b) for key,p in zip(('ab','ba'),originals)}
        estimate=len(motion_bytes(n,ends,header['model'],directions))+224
        if estimate>budget:
            trials.append(dict(kind=kind,a=a,b=b,bytes=estimate,error='size'));continue
        plans=[];proofs=[];errors=[];quality=[]
        try:
            for key,source,target,original in zip(('ab','ba'),ends,ends[::-1],originals):
                plan=reconstruct(directions[key],n,source,target);delta=np.asarray(plan['states'])-np.asarray(original['states'])
                limits=dict(cart=float(np.max(abs(delta[:,0]))),angle=float(np.max(abs(delta[:,1:n+1]))),velocity=float(np.max(abs(delta[:,n+1:]))),force=float(np.max(abs(np.array(plan['forces'])-original['forces']))))
                if limits['cart']>.005 or limits['angle']>.02 or limits['velocity']>.2 or limits['force']>.1:raise ValueError('Reference fidelity: '+str(limits))
                proof=replay(plant,plan,total=plan['duration']+15);history=proof.pop('history')
                if not proof['final_stable'] or proof['max_cart']>=2.304 or proof['max_force']>120.000001 or proof['max_force_rate']>500.000001 or proof['max_tracking_error']>=3:raise ValueError('Physical rejection: '+str(proof))
                direct=intermediate_hold(plant,history[:,1:-1],.02,source,target)
                if not direct['passed']:raise ValueError('Not direct: '+str(direct))
                plan.update(verification=proof,direct_quality=direct);plans.append(plan);proofs.append(proof);errors.append(limits);quality.append(direct)
            fixture=OUT/'scratch'/name.replace('.toml','.fixture.json');worker_path=fixture.with_suffix('.worker.json')
            fixture.write_text(json.dumps([dict(design=designs[p['transition']['target']],source_design=designs[p['transition']['source']],plan=p) for p in plans]),encoding='utf8')
            worker=subprocess.run([r'C:\Program Files\nodejs\node.exe','tests/check-transfers.mjs',str(fixture),str(worker_path)],cwd=ROOT,capture_output=True,encoding='utf8',errors='replace',timeout=300)
            if worker.returncode:raise ValueError('Worker rejection: '+worker.stderr[-1500:])
            verification=json.loads(worker_path.read_bytes())
            for index,(key,plan) in enumerate(zip(('ab','ba'),plans)):
                accepted=dict(individual=[verification['individual'][index]],continuous=[],rail_contacts=verification['rail_contacts'],live_planner_requests=verification['live_planner_requests'])
                plan['worker_verification']=accepted;directions[key]['check']=acceptance_token(plan,proofs[index],accepted)
            encoded=motion_bytes(n,ends,header['model'],directions)
            if len(encoded)>budget:raise ValueError('Final encoded bytes exceed budget')
            (OUT/'motions'/name).write_bytes(encoded)
            for plan in plans:
                t=plan['transition'];(OUT/'plans'/f'{n}-{t["source"]}-{t["target"]}.json.gz').write_bytes(gzip.compress(json.dumps(plan,separators=(',',':')).encode(),compresslevel=3,mtime=0))
            report=dict(file=name,n=n,ends=ends,passed=True,source_bytes=len(raw),bytes=len(encoded),ratio=len(encoded)/len(raw),source_sha256=hashlib.sha256(raw).hexdigest(),sha256=hashlib.sha256(encoded).hexdigest(),method=dict(kind=kind,a=a,b=b),reference_error=errors,physics=proofs,direct=quality,worker=verification,runtime_hashes={key:digest(runtime(p)) for key,p in zip(('ab','ba'),plans)},trials=trials)
            complete.write_text(json.dumps(report,indent=2),encoding='utf8');fixture.unlink();worker_path.unlink();return report
        except Exception as error:
            trials.append(dict(kind=kind,a=a,b=b,bytes=estimate,error=str(error)))
            (OUT/'failures'/name.replace('.toml','.json')).write_text(json.dumps(trials,indent=2),encoding='utf8')
    return dict(file=name,n=n,passed=False,trials=trials)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);parser.add_argument('--only');parser.add_argument('--manifest');args=parser.parse_args()
    if args.manifest:
        from triple_pendulum.build_supercompact import tour_manifest
        tour_manifest(OUT,Path(args.manifest));raise SystemExit
    for folder in ('reports','motions','scratch','plans','failures'):(OUT/folder).mkdir(parents=True,exist_ok=True)
    files=sorted(p.name for p in (ROOT/'dist/极简实验/桌面版/程序文件/motions').glob('*.toml') if not args.only or p.name in args.only.split(','));results=[];start=time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(one,name) for name in files]):
            try:row=future.result()
            except Exception as error:row=dict(passed=False,error=str(error))
            results.append(row);print('ACCEPT' if row['passed'] else 'REJECT',len(results),'/',len(files),row.get('file'),row.get('ratio'),flush=True)
            (OUT/'progress.json').write_text(json.dumps(dict(done=len(results),total=len(files),passed=sum(r['passed'] for r in results),seconds=time.monotonic()-start),indent=2),encoding='utf8')
    (OUT/'summary.json').write_text(json.dumps(dict(passed=all(r['passed'] for r in results),files=results),indent=2),encoding='utf8')
