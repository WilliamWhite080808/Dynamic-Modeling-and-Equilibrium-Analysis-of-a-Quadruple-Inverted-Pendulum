"""Cart-force-only recovery and validated entry into stored trajectory funnels."""
from copy import deepcopy
import time
import numpy as np
from numba import njit
from .model import dynamics,wrap


@njit(cache=True)
def dissipative_force(state,elapsed,rail,max_force,kx,kv,kick):
    d=len(state)//2;x=state[0];v=state[d]
    spring=.4*max_force;damper=.6*max_force
    position=kx*(x+.5*x*x*x/(rail*rail))
    force=-spring*np.tanh(position/spring)-damper*np.tanh(kv*v/damper)
    if elapsed<.6:force+=kick*np.sin(2*np.pi*elapsed/.6)*np.sin(np.pi*elapsed/.6)**2
    return min(max_force,max(-max_force,force))


@njit(cache=True)
def dissipative_rollout(initial,total,rail,max_force,kx,kv,kick,H,a,total_mass,gravity,damping,cart_damping):
    count=int(round(total/.004));states=np.empty((count+1,len(initial)));forces=np.empty(count+1)
    state=initial.copy();states[0]=state;forces[0]=0.;used=0
    for k in range(count):
        force=dissipative_force(state,k*.004,rail,max_force,kx,kv,kick)
        for j in range(4):
            f1=dynamics(state,force,H,a,total_mass,gravity,damping,cart_damping)
            f2=dynamics(state+.0005*f1,force,H,a,total_mass,gravity,damping,cart_damping)
            f3=dynamics(state+.0005*f2,force,H,a,total_mass,gravity,damping,cart_damping)
            f4=dynamics(state+.001*f3,force,H,a,total_mass,gravity,damping,cart_damping)
            state=state+.001/6*(f1+2*f2+2*f3+f4)
        states[k+1]=state;forces[k+1]=force;used=k+1
        if abs(state[0])>=rail*.97 or not np.isfinite(state).all():break
    return states[:used+1],forces[:used+1]


def critical_kick(initial,plant,goal):
    if np.max(abs(wrap(initial[1:plant.d]-goal)))<.1:return 0.
    if np.max(abs(np.sin(initial[1:plant.d])))<.01 and np.max(abs(initial[plant.d:]))<.01:
        return -12. if initial[0]>.2 else 12.
    return 0.


def trim_reference(template,index,initial):
    result=deepcopy(template)
    for key in ('states','forces','derivatives','gains'):result[key]=result[key][index:]
    result.update(initial=np.asarray(initial).tolist(),duration=(len(result['states'])-1)*result['dt'])
    for key in ('verification','repository_id','precomputed'):result.pop(key,None)
    return result


def funnel_candidates(states,template):
    """Candidate hints only. They are admitted by nonlinear physical replay."""
    d=states.shape[1]//2
    indices=np.arange(0,len(template['states'])-2,max(1,round(.16/template['dt'])))
    reference=np.asarray(template['states'])[indices]
    delta=states[:,None,:]-reference[None,:,:];delta[:,:,1:d]=wrap(delta[:,:,1:d])
    cost=np.sum(delta**2*np.r_[np.ones(d),np.ones(d)*.025],axis=2)
    feasible=(np.max(abs(delta[:,:,1:d]),axis=2)<.45)&(np.max(abs(delta[:,:,d:]),axis=2)<1.5)&(abs(delta[:,:,0])<.4)&(cost<.45)
    ranked=np.where(feasible,cost,np.inf);best=np.argmin(ranked,axis=1)
    return indices[best],ranked[np.arange(len(states)),best]


def recover_plan(plant,initial,goal,cancel=None,progress=None,max_settle=90.):
    from . import precomputed
    from .validate_plan import replay
    started=time.perf_counter();initial=np.asarray(initial).copy()
    def status(phase,**values):
        if cancel is not None and cancel.is_set():raise InterruptedError('已取消恢复搜索')
        if progress:progress(dict(phase=phase,**values))
    def validate(candidate):
        status('独立验证恢复路径',horizon=candidate['duration'])
        report=replay(plant,candidate,total=candidate['duration']+20,cancel=cancel);history=report.pop('history')
        passed=report['final_stable'] and report['max_cart']<plant.p.rail*.96 and report['max_tracking_error']<3
        if passed:
            candidate.update(success=True,verification=report,parameters=plant.p.dict(),wall_seconds=time.perf_counter()-started,
                source='耗散恢复 + 轨迹接入',validation='完整非线性闭环恢复验收通过')
            return candidate,history
        return None
    if np.max(abs(wrap(initial[1:plant.d]-goal)))<.8:
        direct=dict(initial=initial.tolist(),target_angles=np.asarray(goal).tolist(),duration=8.,segments=[dict(kind='balance',duration=8.)])
        result=validate(direct)
        if result:return result
    template=precomputed.lookup(plant,precomputed.hanging(plant),goal)
    if template is None:return None
    indices,cost=funnel_candidates(initial[None,:],template)
    if np.isfinite(cost[0]):
        result=validate(trim_reference(template,int(indices[0]),initial))
        if result:return result
    for profile,(kx,kv) in enumerate([(8.,6.),(18.,12.),(30.,24.)]):
        status('模拟耗散恢复，寻找可接入的起摆状态',search=profile+1,horizon=max_settle)
        kick=critical_kick(initial,plant,goal)
        states,forces=dissipative_rollout(initial,max_settle,plant.p.rail,plant.p.max_force,kx,kv,kick,*plant.args)
        sample=np.arange(50,len(states),50);times=sample*.004
        if not len(sample):continue
        indices,cost=funnel_candidates(states[sample],template)
        possible=np.flatnonzero(np.isfinite(cost));chosen=[]
        # Check early useful entries first, retaining later calm states instead
        # of exhausting the budget on almost identical points in one swing.
        for k in possible:
            if not chosen or times[k]-times[chosen[-1]]>=.8:chosen.append(int(k))
            if len(chosen)>=16:break
        for t in (20.,30.,45.,60.,80.):
            k=int(round(t/.2))-1
            if 0<=k<len(sample) and np.isfinite(cost[k]) and k not in chosen:chosen.append(k)
        for k in chosen:
            status('检验轨迹接入点',search=profile+1,capture_time=float(times[k]),reference_time=float(indices[k]*template['dt']))
            leaf=trim_reference(template,int(indices[k]),states[sample[k]])
            leaf_report=replay(plant,leaf,total=leaf['duration']+15,cancel=cancel);leaf_report.pop('history')
            if not leaf_report['final_stable'] or leaf_report['max_cart']>=plant.p.rail*.96 or leaf_report['max_tracking_error']>=3:continue
            duration=float(times[k]);candidate=dict(initial=initial.tolist(),target_angles=np.asarray(goal).tolist(),duration=duration+leaf['duration'],
                segments=[dict(kind='dissipate',duration=duration,policy=dict(version=1,kx=kx,kv=kv,kick=kick)),dict(kind='track',duration=leaf['duration'],plan=leaf)],
                recovery=dict(capture_time=duration,reference_time=float(indices[k]*template['dt']),profile=profile))
            result=validate(candidate)
            if result:return result
    return None


if __name__=='__main__':
    from .model import Plant,Parameters
    for n in range(1,6):
        p=Plant(Parameters(n=n));rng=np.random.default_rng(720+n)
        x=np.zeros(p.dim);x[0]=.3;x[1:p.d]=rng.uniform(-np.pi,np.pi,n);x[p.d:]=rng.uniform(-.8,.8,p.d)
        start=time.perf_counter()
        for kx,kv in [(18.,12.),(8.,6.),(30.,24.)]:
            states,forces=dissipative_rollout(x,100,p.p.rail,p.p.max_force,kx,kv,0.,*p.args)
            angle=np.max(abs(wrap(states[:,1:p.d]-np.pi)),axis=1)
            velocity=np.max(abs(states[:,p.d:]),axis=1)
            matches=np.flatnonzero((angle<.25)&(velocity<.6)&(abs(states[:,0])<.25))
            print(n,kx,kv,'capture',float(matches[0]*.004) if len(matches) else None,'rail',float(np.max(abs(states[:,0]))),'time',round(time.perf_counter()-start,2),flush=True)
