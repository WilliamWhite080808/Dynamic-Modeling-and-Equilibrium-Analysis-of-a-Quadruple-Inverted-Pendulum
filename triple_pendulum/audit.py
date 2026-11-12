"""Reproducible audit of the five passive, fully hanging initial conditions."""
from pathlib import Path
import json
import numpy as np
from .model import Plant,Parameters
from .planner import tracking_gains
from .validate_plan import replay

def main():
    root=Path(__file__).resolve().parent.parent
    reports=[]
    for n in range(1,6):
        filename=f'optimal-{n}.json' if n>=3 else f'swingup-{n}.json'
        if n==5:filename='optimal-5-fine-gains.json'
        data=json.loads((root/'results'/filename).read_text(encoding='utf8'))
        p=Plant(Parameters(n=n));initial=np.array(data['initial'])
        assert np.max(abs(initial[1:p.d]-np.pi))<1e-12
        assert np.max(abs(initial[p.d:]))==0
        data['gains']=tracking_gains(p,data)
        result=replay(p,data,total=data['duration']+10);history=result.pop('history')
        passed=bool(result['final_stable'] and result['max_cart']<p.p.rail*.96 and result['max_force']<=p.p.max_force and result['max_tracking_error']<3)
        data.update(verification=result,parameters=p.p.dict(),success=passed)
        (root/'results'/f'verified-{n}.json').write_text(json.dumps(data),encoding='utf8')
        np.savez(root/'results'/f'audit-{n}.npz',history=history)
        row=dict(order=n,passed=passed,initial='all rods pi, all velocities zero',duration=data['duration'],**result)
        reports.append(row);print(json.dumps(row),flush=True)
    (root/'results'/'acceptance.json').write_text(json.dumps(reports,indent=2),encoding='utf8')
    if not all(r['passed'] for r in reports):raise SystemExit(1)

if __name__=='__main__':main()
