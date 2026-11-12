"""Reproducible arbitrary-initial-state campaign, storing only physical successes."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import json,time
import numpy as np
from .model import Plant,Parameters
from . import repository


def cases(random_per_order=5):
    result=[]
    for n in range(1,6):
        rng=np.random.default_rng(720+n);p=Plant(Parameters(n=n))
        x=np.zeros(p.dim);x[0]=.3;x[1:p.d]=rng.uniform(-np.pi,np.pi,n);x[p.d:]=rng.uniform(-.8,.8,p.d)
        for code in repository.patterns(n):result.append(dict(name=f'{n}-all-targets-{code}',order=n,initial=x.tolist(),pattern=code))
        for i in range(random_per_order):
            x=np.r_[rng.uniform(-.8,.8),rng.uniform(-np.pi,np.pi,n),rng.uniform(-.6,.6),rng.uniform(-3,3,n)]
            result.append(dict(name=f'{n}-random-{i}',order=n,initial=x.tolist(),pattern='U'*n))
        for i in range(2):
            x=np.r_[(-1 if i else 1)*1.7,rng.uniform(-np.pi,np.pi,n),(-1 if i else 1)*.7,rng.uniform(-2,2,n)]
            result.append(dict(name=f'{n}-rail-side-{i}',order=n,initial=x.tolist(),pattern='U'*n))
        if n>=2:
            x=np.zeros(p.dim);x[1:p.d]=repository.angles('U'+'D'*(n-1))
            result.append(dict(name=f'{n}-exact-other-equilibrium',order=n,initial=x.tolist(),pattern='U'*n))
    return result


def solve(case):
    from .recovery import recover_plan
    started=time.perf_counter();p=Plant(Parameters(n=case['order']))
    def progress(info):
        if time.perf_counter()-started>100:raise TimeoutError('恢复测试单例达到预算')
    try:
        result=recover_plan(p,np.array(case['initial']),np.array(repository.angles(case['pattern'])),progress=progress)
        if result:
            plan,history=result;meta=repository.store(plan,p,history,title='初值恢复实验 → '+repository.label(case['pattern']))
            return dict(**case,success=True,wall_seconds=time.perf_counter()-started,duration=plan['duration'],repository_id=meta['id'],verification=plan['verification'])
        return dict(**case,success=False,wall_seconds=time.perf_counter()-started)
    except Exception as error:return dict(**case,success=False,wall_seconds=time.perf_counter()-started,error=str(error))


def stress_cases():
    result=[]
    for n in range(1,6):
        rng=np.random.default_rng(8600+n)
        for i in range(10):
            x=np.r_[rng.uniform(-1.6,1.6),rng.uniform(-np.pi,np.pi,n),rng.uniform(-1.5,1.5),rng.uniform(-6,6,n)]
            code='U'*n if i<5 else str(rng.choice(repository.patterns(n)))
            result.append(dict(name=f'{n}-stress-{i}',order=n,initial=x.tolist(),pattern=code))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=2);parser.add_argument('--random',type=int,default=5);parser.add_argument('--stress',action='store_true');args=parser.parse_args()
    output=Path('results/recovery-stress-audit.json' if args.stress else 'results/recovery-audit.json');results=[];inputs=stress_cases() if args.stress else cases(args.random)
    with ProcessPoolExecutor(max_workers=max(1,min(2,args.workers))) as pool:
        futures=[pool.submit(solve,case) for case in inputs]
        for future in as_completed(futures):
            row=future.result();results.append(row)
            report=dict(total=len(inputs),completed=len(results),passed=sum(r['success'] for r in results),cases=results)
            temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(output)
            print('PASS' if row['success'] else 'FAIL',row['name'],'wall',round(row['wall_seconds'],2),'duration',row.get('duration'),flush=True)
    print('RECOVERY RESULT',sum(r['success'] for r in results),'/',len(inputs),flush=True)

if __name__=='__main__':main()
