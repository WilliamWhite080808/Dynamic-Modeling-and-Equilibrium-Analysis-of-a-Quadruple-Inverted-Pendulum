import json
from pathlib import Path
import numpy as np
from .model import Plant,Parameters,wrap
from .control import lqr

def replay(plant,plan,dt=0.001,total=13,cancel=None):
    x=np.array(plan['initial']);d=plant.d;goal=np.array(plan.get('target_angles',[0.]*plant.n));K=lqr(plant,target=goal)[0][0];history=[];u=0
    max_cart=0.;max_force=0.;max_force_rate=0.;stable_since=None;settled=None;max_tracking=0.
    for k in range(round(total/dt)):
        if k%500==0 and cancel is not None and cancel.is_set():raise InterruptedError('已取消旧规划')
        t=k*dt
        if k%4==0:
            previous_force=u
            active=plan;elapsed=t;kind='track'
            if t<plan['duration'] and plan.get('segments'):
                for index,segment in enumerate(plan['segments']):
                    if elapsed<segment['duration']-1e-10 or index==len(plan['segments'])-1:
                        kind=segment['kind'];active=segment.get('plan',segment);elapsed=max(0.,min(elapsed,segment['duration']));break
                    elapsed=max(0.,elapsed-segment['duration'])
            if t<plan['duration'] and kind=='dissipate':
                from .recovery import dissipative_force
                policy=active['policy'];u=dissipative_force(x,elapsed,plant.p.rail,plant.p.max_force,policy['kx'],policy['kv'],policy.get('kick',0.))
            elif t<plan['duration'] and kind=='track':
                z=elapsed/active['dt'];j=min(int(z),len(active['states'])-2);a=z-j
                ref=np.array(active['states'][j])*(1-a)+np.array(active['states'][j+1])*a
                if 'derivatives' in active:
                    h=active['dt']; ref=(2*a**3-3*a*a+1)*np.array(active['states'][j])+(a**3-2*a*a+a)*h*np.array(active['derivatives'][j])+(-2*a**3+3*a*a)*np.array(active['states'][j+1])+(a**3-a*a)*h*np.array(active['derivatives'][j+1])
                gain=np.array(active['gains'][j])*(1-a)+np.array(active['gains'][j+1])*a
                delta=x-ref;delta[1:d]=wrap(delta[1:d])
                max_tracking=max(max_tracking,float(np.sum(delta**2*np.r_[np.ones(d),np.ones(d)*.025])))
                u=(1-a)*active['forces'][j]+a*active['forces'][j+1]-gain@delta
            else:
                error=x.copy();error[1:d]=wrap(error[1:d]-goal);u=-K@error
            if t>=plan['duration'] and abs(x[0])>plant.p.rail*.78:
                sign=np.sign(x[0]);u-=sign*(65*(abs(x[0])-plant.p.rail*.78)+18*max(0,sign*x[d]))
            u=float(np.clip(u,-plant.p.max_force,plant.p.max_force))
            if plan.get('force_rate'):u=float(np.clip(u,previous_force-plan['force_rate']*4*dt,previous_force+plan['force_rate']*4*dt))
            max_force_rate=max(max_force_rate,abs(u-previous_force)/(4*dt))
        x=plant.rk4(x,u,dt)
        max_cart=max(max_cart,abs(float(x[0])));max_force=max(max_force,abs(u))
        stable=np.max(abs(wrap(x[1:d]-goal)))<np.deg2rad(.5) and np.max(abs(x[d+1:]))<.03 and abs(x[0])<.03 and (not plan.get('strict_rest') or abs(x[d])<.03)
        if stable:
            if stable_since is None:stable_since=t+dt
            if t+dt-stable_since>=1 and settled is None:settled=stable_since
        else:stable_since=None
        if k%20==0: history.append([t,*x,u])
        if not np.isfinite(x).all() or np.max(abs(x))>1e5:break
    history=np.array(history)
    return dict(final_state=x.tolist(),final_angle_deg=float(np.max(abs(wrap(x[1:d]-goal)))*180/np.pi),max_cart=max_cart,max_force=max_force,max_force_rate=max_force_rate,settled_at=settled,final_stable=bool(stable_since is not None and total-stable_since>=1),max_tracking_error=max_tracking,history=history)

if __name__=='__main__':
    import sys
    n=int(sys.argv[1]) if len(sys.argv)>1 else 3
    path=Path('results')/f'swingup-{n}.json';p=Plant(Parameters(n=n));info=replay(p,json.loads(path.read_text()))
    np.savez(Path('results')/f'replay-{n}.npz',history=info.pop('history'))
    print(json.dumps(info,indent=2))
