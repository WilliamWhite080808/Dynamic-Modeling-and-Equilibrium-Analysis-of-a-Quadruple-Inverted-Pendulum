"""Generate and independently verify all seven non-hanging triple equilibria."""
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
from .model import Plant,Parameters
from .optimal import optimize
from .validate_plan import replay
from . import repository

def main():
    root=Path(__file__).resolve().parent.parent
    p=Plant(Parameters());initial=np.zeros(p.dim);initial[1:p.d]=np.pi
    base=json.loads((root/'results'/'verified-3.json').read_text());base['target_angles']=[0.]*3
    candidates={'UUU':base};summary=[]
    for code in ['UUU','UUD','UDD','UDU','DDU','DUU','DUD']:
        print('TARGET',code,flush=True)
        result=base if code=='UUU' else None
        if result is None:
            existing=repository.nearest_template(p,initial,repository.angles(code))
            if existing is not None:result=existing
        if result is None:
            nearest=min(candidates,key=lambda k:sum(a!=b for a,b in zip(k,code)))
            guess=candidates[nearest]
            for duration in (5.,6.5):
                result=optimize(p,initial,duration,241,guess,max_iter=600,max_seconds=55,target_angles=repository.angles(code))
                if result['success']:
                    check=replay(p,result,total=duration+8);check.pop('history')
                    if check['final_stable'] and check['max_cart']<p.p.rail*.96:break
                guess=result if result.get('gains') else guess
        report=replay(p,result,total=result['duration']+8) if result.get('gains') else None
        success=bool(report and report['final_stable'] and report['max_cart']<p.p.rail*.96 and report['max_tracking_error']<3)
        if success:
            history=report.pop('history');result['verification']=report;result['parameters']=p.p.dict();result['success']=True
            meta=repository.store(result,p,history,title='完全下垂静止 → '+repository.label(code));candidates[code]=result
            variant=deepcopy(result);variant['initial']=(initial+np.array([.05,.012,-.009,.006,0.,.01,-.01,.005])).tolist()
            v=replay(p,variant,total=result['duration']+8)
            if v['final_stable'] and v['max_cart']<p.p.rail*.96 and v['max_tracking_error']<3:
                vh=v.pop('history');variant['verification']=v;repository.store(variant,p,vh,title='近下垂扰动初值 → '+repository.label(code))
            print('PASS',code,report,flush=True)
        else:print('NOT VERIFIED',code,flush=True)
        summary.append(dict(pattern=code,success=success))
        (root/'results'/'seven-targets.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    if not all(row['success'] for row in summary):raise SystemExit(1)

if __name__=='__main__':main()
