"""Populate seven genuine local convergence experiments and capture variations."""
import numpy as np
from .model import Plant,Parameters
from .control import lqr
from .validate_plan import replay
from . import repository

def main():
    p=Plant(Parameters())
    for code in repository.PATTERNS:
        goal=np.array(repository.angles(code));K=lqr(p,target=goal)[0][0]
        initial=np.zeros(p.dim);initial[0]=.07;initial[1:p.d]=goal+.025*np.cos(goal);initial[p.d+1:]=.015*np.cos(goal)
        plan=dict(initial=initial.tolist(),target_angles=goal.tolist(),duration=0.,dt=.001,
                  states=[initial.tolist(),np.r_[0,goal,np.zeros(p.d)].tolist()],forces=[0.,0.],gains=[K.tolist(),K.tolist()],derivatives=[p.rhs(initial).tolist(),np.zeros(p.dim).tolist()],success=True,parameters=p.p.dict())
        r=replay(p,plan,total=12);history=r.pop('history')
        assert r['final_stable'] and r['max_cart']<p.p.rail*.96,(code,r)
        plan['verification']=r;repository.store(plan,p,history,title='近目标扰动 → '+repository.label(code))
        print(code,'LOCAL PASS',r['final_angle_deg'],flush=True)
    # Every variant is checked against its own true initial state before insertion.
    variations=[np.array([-.18,.025,-.018,.012,0,.025,-.02,.01]),np.array([.18,-.02,.014,-.01,.03,-.015,.01,-.005]),np.array([0,.04,.04,.04,0,0,0,0])]
    rows=[r for r in repository.catalog() if r['order']==3 and np.max(abs(np.array(r['initial'])[1:4]-np.pi))<1e-9]
    for row in rows:
        base=repository.read(row['id'])['control_plan']
        for offset in variations:
            data={**base,'initial':(np.array(base['initial'])+offset).tolist()}
            r=replay(p,data,total=max(12,data['duration']+8));history=r.pop('history')
            if r['final_stable'] and r['max_cart']<p.p.rail*.96 and r['max_tracking_error']<3:
                data['verification']=r;repository.store(data,p,history,title='近下垂初值 → '+repository.label(row['pattern']))
    print('repository entries',len(repository.catalog()),flush=True)

if __name__=='__main__':main()
