from dataclasses import dataclass
import time
import numpy as np
from scipy.integrate import solve_ivp
from .model import Plant,Parameters,wrap
from .control import lqr,Observer,measurement


def simulate(p=None,duration=12,dt=0.001,initial=None,mode='lqr',sensor='full_state',observer='kalman',reference=False,seed=42,noise=0.0):
    plant=Plant(p);d=plant.d;K=lqr(plant)[0][0]
    x=np.zeros(plant.dim) if initial is None else np.array(initial,dtype=float)
    if initial is None:x[1:d]=0.012
    estimator=Observer(Plant(plant.p),sensor,observer)
    rng=np.random.default_rng(seed);u=0.;rows=[];last_stable=None;settled=None;saturation=0;contacts=0;nfev=0
    start=time.perf_counter();step_times=[]
    for k in range(round(duration/dt)):
        t=k*dt
        if k%4==0:
            y=measurement(plant,x,sensor)+noise*rng.normal(size=len(measurement(plant,x,sensor)))
            estimated=estimator.update(y,u,dt*4,max(noise,0.002))
            error=(x if sensor=='full_state' else estimated).copy();error[1:d]=wrap(error[1:d])
            command=0. if mode=='off' else float(-K@error)
            u=float(np.clip(command,-plant.p.max_force,plant.p.max_force));saturation+=abs(command)>plant.p.max_force
        step_start=time.perf_counter()
        if reference:
            sol=solve_ivp(lambda t,s:plant.rhs(s,u),(t,t+dt),x,method='DOP853',rtol=1e-11,atol=1e-13)
            x=sol.y[:,-1];nfev+=sol.nfev
        else:x=plant.rk4(x,u,dt);nfev+=4
        # Frictionless unilateral rail impact with restitution 0.05.
        if abs(x[0])>plant.p.rail:
            sign=np.sign(x[0]);x[0]=sign*plant.p.rail;contacts+=1
            if sign*x[d]>0:
                normal=np.linalg.solve(plant.mass_matrix(x[:d]),np.eye(d)[:,0])
                x[d:]-=(1.05)*x[d]/normal[0]*normal
        step_times.append(time.perf_counter()-step_start)
        is_stable=np.max(abs(wrap(x[1:d])))<np.deg2rad(.5) and np.max(abs(x[d:]))<.03 and abs(x[0])<.03
        if is_stable:
            if last_stable is None:last_stable=t
            if t-last_stable>=1 and settled is None:settled=last_stable
        else:last_stable=None
        if k%20==0:rows.append([t+dt,*x,*estimator.x,u,plant.energy(x)])
        if not np.isfinite(x).all() or max(abs(x))>1e5:raise FloatingPointError('Simulation diverged')
    elapsed=time.perf_counter()-start
    arr=np.array(rows)
    return arr,dict(order=plant.n,solver='DOP853' if reference else 'RK4',dt=dt,seed=seed,duration=duration,
        wall_seconds=elapsed,realtime_ratio=duration/elapsed,rhs_per_second=nfev/elapsed,
        step_mean_ms=np.mean(step_times)*1000,step_p95_ms=np.percentile(step_times,95)*1000,
        final_angle_deg=float(np.max(abs(wrap(x[1:d])))*180/np.pi),final_cart=float(x[0]),
        settled_at=settled,final_stable=bool(last_stable is not None and duration-last_stable>=1),
        saturation_ratio=float(saturation/(round(duration/dt)/4)),contacts=contacts,
        max_force=float(np.max(abs(arr[:,-2]))),max_cart=float(np.max(abs(arr[:,1]))),
        final_estimation_error=float(np.linalg.norm(x-estimator.x)),parameters=plant.p.dict(),nfev=nfev)
