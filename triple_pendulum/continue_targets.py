"""Endpoint continuation for difficult all-down to mixed-equilibrium transitions."""
import numpy as np
from .model import Plant,Parameters
from .optimal import optimize
from .validate_plan import replay
from . import repository

def main():
    p=Plant(Parameters());initial=np.zeros(p.dim);initial[1:p.d]=np.pi
    base=repository.nearest_template(p,initial,[0.]*3)
    for code in ['UUD','UDU','DUU','DUD']:
        guess=base
        print('CONTINUE',code,flush=True)
        mask=np.array([c=='D' for c in code]);good=True
        for fraction in [.2,.4,.6,.8,1.]:
            goal=2*np.pi-np.pi*fraction*mask
            result=optimize(p,initial,6.5,161,guess,max_iter=230,max_seconds=22,target_angles=goal,compute_gains=False)
            print(code,fraction,'defect',result['defect'],flush=True)
            if not result['success']:good=False;break
            guess=result
        if not good:continue
        result=optimize(p,initial,6.5,321,guess,max_iter=300,max_seconds=35,target_angles=repository.angles(code))
        if not result['success']:continue
        report=replay(p,result,total=15);history=report.pop('history')
        if report['final_stable'] and report['max_cart']<p.p.rail*.96 and report['max_tracking_error']<3:
            result['verification']=report;result['parameters']=p.p.dict();repository.store(result,p,history,title='完全下垂静止 → '+repository.label(code));print('CONTINUATION PASS',code,report,flush=True)
        else:print('CONTINUATION NOT VERIFIED',code,flush=True)

if __name__=='__main__':main()
