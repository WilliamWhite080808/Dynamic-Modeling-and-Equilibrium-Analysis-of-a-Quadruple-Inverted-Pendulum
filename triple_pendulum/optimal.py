"""Hard-constrained swing-up NLP using CasADi AD and IPOPT.

The plant, not this planning transcription, determines all displayed motion.
Reference: Tedrake, Underactuated Robotics, Trajectory Optimization / TVLQR.
"""
import sys
import os
import time
from pathlib import Path
import numpy as np
try:
    import casadi as ca
except ImportError:
    vendor=Path(__file__).resolve().parent.parent/'.vendor'
    if vendor.exists():sys.path.insert(0,str(vendor))
    import casadi as ca
if os.name=='nt':
    # CasADi's plugin loader uses narrow Windows paths; the project folder may be Chinese.
    # Keep the DLL directory wide, and pass an ASCII relative plugin path when possible.
    _casadi_dir=Path(ca.__file__).resolve().parent
    _dll_handle=os.add_dll_directory(str(_casadi_dir))
    try:_relative=os.path.relpath(_casadi_dir)
    except ValueError:_relative=str(_casadi_dir)  # packed runtime may live on another drive
    if not _relative.isascii():
        import ctypes
        _short=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(str(_casadi_dir),_short,len(_short)) and _short.value.isascii():_relative=_short.value
        else:
            # CasADi uses LoadLibraryA; an NTFS volume may have no 8.3 names.
            # Preload through the Unicode API. Its later basename lookup then
            # reuses these exact modules without interpreting a UTF-8 path.
            ctypes.windll.kernel32.SetDllDirectoryW(str(_casadi_dir));_relative=''
            _plugin_handles=[ctypes.WinDLL(str(p)) for p in sorted(_casadi_dir.glob('libcasadi_linsol_*.dll'))]
            _plugin_handles += [ctypes.WinDLL(str(_casadi_dir/'libcasadi_nlpsol_ipopt.dll'))]
    ca.GlobalOptions.setCasadiPath(_relative if _relative.isascii() else str(_casadi_dir))
from .model import Plant,Parameters,wrap
from .planner import tracking_gains


def symbolic_dynamics(plant):
    d=plant.d;n=plant.n;p=plant.p
    s=ca.MX.sym('s',plant.dim);u=ca.MX.sym('u');q=s[:d];v=s[d:]
    angles=q[1:];w=v[1:];a=ca.DM(plant.a)
    cos=ca.cos(angles)
    M=ca.vertcat(ca.horzcat(plant.args[2],(a*cos).T),ca.horzcat(a*cos,ca.DM(plant.H)*ca.cos(ca.repmat(angles,1,n)-ca.repmat(angles.T,n,1))))
    b0=u-p.cart_damping*v[0]+ca.dot(a*ca.sin(angles),w*w)
    bias=ca.DM(plant.H)*ca.sin(ca.repmat(angles,1,n)-ca.repmat(angles.T,n,1))
    b=p.gravity*a*ca.sin(angles)-ca.mtimes(bias,w*w)
    damping=np.zeros((n,n))
    damping[0,0]+=p.damping
    for i in range(1,n):
        damping[i-1,i-1]+=p.damping;damping[i,i]+=p.damping
        damping[i-1,i]-=p.damping;damping[i,i-1]-=p.damping
    b-=ca.mtimes(ca.DM(damping),w)
    return ca.Function('dynamics',[s,u],[ca.vertcat(v,ca.solve(M,ca.vertcat(b0,b)))])


def optimize(plant,initial,duration=5,nodes=201,guess=None,max_iter=1500,seed=42,cancel=None,max_seconds=180,progress=None,target_angles=None,compute_gains=True,endpoint_angles=None,initial_force=None,force_rate=None,force_fraction=.66,transcription='hermite-simpson',reference_weight=0.):
    if not 0<force_fraction<=1:raise ValueError('Force fraction must remain inside the physical actuator limit')
    if transcription not in ('hermite-simpson','rk4'):raise ValueError('Unknown transcription')
    start=time.perf_counter();m=plant.dim;d=plant.d;h=duration/(nodes-1)
    initial=np.asarray(initial,dtype=float);goal=np.zeros(plant.n) if target_angles is None else np.asarray(target_angles)
    target=np.zeros(m);target[1:d]=initial[1:d]-wrap(initial[1:d]-goal)
    if endpoint_angles is not None:target[1:d]=np.asarray(endpoint_angles)
    f=symbolic_dynamics(plant);opti=ca.Opti();X=opti.variable(m,nodes);U=opti.variable(1,nodes)
    fs=f.map(nodes)(X,U)
    if transcription=='rk4':
        stage=f.map(nodes-1);left=X[:,:-1];um=(U[:,:-1]+U[:,1:])/2
        k1=fs[:,:-1];k2=stage(left+h/2*k1,um);midpoint=left+h/2*k2
        k3=stage(midpoint,um);k4=stage(left+h*k3,U[:,1:])
        defect=X[:,1:]-left-h/6*(k1+2*k2+2*k3+k4)
    else:
        midpoint=(X[:,:-1]+X[:,1:])/2+h/8*(fs[:,:-1]-fs[:,1:])
        fm=f.map(nodes-1)(midpoint,(U[:,:-1]+U[:,1:])/2)
        defect=X[:,1:]-X[:,:-1]-h/6*(fs[:,:-1]+4*fm+fs[:,1:])
    opti.subject_to(defect==0)
    opti.subject_to(X[:,0]==initial);opti.subject_to(X[:,-1]==target)
    opti.subject_to(opti.bounded(-plant.p.rail*.82,X[0,:],plant.p.rail*.82))
    # Bound midpoint positions too, not only mesh nodes.
    opti.subject_to(opti.bounded(-plant.p.rail*.84,midpoint[0,:],plant.p.rail*.84))
    opti.subject_to(opti.bounded(-plant.p.max_force*force_fraction,U,plant.p.max_force*force_fraction))
    opti.subject_to(U[0,-1]==0)
    if initial_force is not None:opti.subject_to(U[0,0]==initial_force)
    if force_rate is not None:opti.subject_to(opti.bounded(-force_rate*h,U[:,1:]-U[:,:-1],force_rate*h))
    objective=h*(0.001*ca.sumsqr(U)+0.01*ca.sumsqr(X[0,:]))+0.0002*ca.sumsqr(U[:,1:]-U[:,:-1])
    opti.minimize(objective)
    t=np.linspace(0,1,nodes);z=initial[None,:]+(3*t*t-2*t*t*t)[:,None]*(target-initial)[None,:]
    z[:,d:]=6*(t-t*t)[:,None]/duration*(target-initial)[None,:d]
    u=10*np.sin(4*np.pi*t);z[:,0]=.5*np.sin(2*np.pi*t)*np.sin(np.pi*t)
    if guess is not None:
        old=np.linspace(0,1,len(guess['states']));oldx=np.array(guess['states'])
        for j in range(m):z[:,j]=np.interp(t,old,oldx[:,j])
        z[:,d:]*=guess.get('duration',duration)/duration
        u=np.interp(t,old,guess['forces'])
        end_correction=target[:d]-z[-1,:d]
        blend=3*t*t-2*t*t*t
        z[:,:d]+=blend[:,None]*end_correction
        z[:,d:]+=(6*t*(1-t)/duration)[:,None]*end_correction
        # Match the actual initial position/velocity in the warm start, smoothly
        # fading the correction to zero. This changes only NLP variables.
        bridge=duration*.45;tt=t*duration;alpha=np.minimum(tt/bridge,1)
        dq=initial[:d]-z[0,:d];dv=initial[d:]-z[0,d:]
        h00=2*alpha**3-3*alpha**2+1;h10=alpha**3-2*alpha**2+alpha
        z[:,:d]+=h00[:,None]*dq+bridge*h10[:,None]*dv
        dh00=(6*alpha**2-6*alpha)/bridge;dh10=3*alpha**2-4*alpha+1
        dh00[alpha>=1]=0;dh10[alpha>=1]=0
        z[:,d:]+=dh00[:,None]*dq+dh10[:,None]*dv
    elif seed!=42:
        rng=np.random.default_rng(seed);z[:,1:d]+=.1*np.sin(np.pi*t)[:,None]*rng.normal(size=plant.n)[None,:]
    opti.set_initial(X,z.T);opti.set_initial(U,u[None,:])
    if reference_weight:
        if guess is None or reference_weight<0:raise ValueError('Reference projection requires a warm input and positive weight')
        opti.minimize(opti.f+reference_weight*ca.sumsqr(X-ca.DM(z.T)))
    feasible_guess=None;iterations=0
    def callback(iteration):
        nonlocal feasible_guess,iterations
        iterations=iteration
        if cancel is not None and cancel.is_set():raise InterruptedError('已取消旧规划')
        if time.perf_counter()-start>max_seconds:raise TimeoutError('本轮起摆搜索达到时间预算')
        if progress and iteration%10==0:progress(iteration)
        if iteration>=8 and iteration%8==0:
            constraint_error=float(np.max(abs(np.array(opti.debug.value(defect)))))
            terminal_error=float(np.linalg.norm(np.array(opti.debug.value(X[:,-1])).ravel()-target))
            if constraint_error<1e-8 and terminal_error<1e-8:
                feasible_guess=(np.array(opti.debug.value(X)).T,np.array(opti.debug.value(U)).reshape(-1))
    opti.callback(callback)
    opti.solver('ipopt',{'print_time':False},{'print_level':0,'max_iter':max_iter,'tol':1e-8,'acceptable_tol':1e-6,'max_cpu_time':max_seconds,'mu_strategy':'adaptive','sb':'yes'})
    solved=True
    try:
        solution=opti.solve();states=np.array(solution.value(X)).T;forces=np.array(solution.value(U)).reshape(-1)
    except RuntimeError:
        if cancel is not None and cancel.is_set():raise InterruptedError('已取消旧规划')
        solved=False;states=np.array(opti.debug.value(X)).T;forces=np.array(opti.debug.value(U)).reshape(-1)
        if feasible_guess is not None:states,forces=feasible_guess
    derivatives=plant.batch(states.copy(),forces.copy())
    if transcription=='rk4':
        left=states[:-1];um=(forces[:-1]+forces[1:])/2;k1=derivatives[:-1]
        k2=plant.batch((left+h/2*k1).copy(),um.copy());k3=plant.batch((left+h/2*k2).copy(),um.copy())
        k4=plant.batch((left+h*k3).copy(),forces[1:].copy())
        err=states[1:]-left-h/6*(k1+2*k2+2*k3+k4)
    else:
        mid=(states[:-1]+states[1:])/2+h/8*(derivatives[:-1]-derivatives[1:])
        fm_num=plant.batch(mid.copy(),((forces[:-1]+forces[1:])/2).copy())
        err=states[1:]-states[:-1]-h/6*(derivatives[:-1]+4*fm_num+derivatives[1:])
    defect_error=float(np.max(abs(err)));terminal=float(np.linalg.norm(states[-1]-target))
    info=dict(duration=duration,dt=h,states=states.tolist(),forces=forces.tolist(),derivatives=derivatives.tolist(),
        initial=initial.tolist(),target_angles=goal.tolist(),defect=defect_error,terminal_error=terminal,nfev=iterations,
        wall_seconds=time.perf_counter()-start,solver='CasADi / IPOPT · '+('RK4 multiple shooting' if transcription=='rk4' else 'Hermite–Simpson'),
        success=bool(defect_error<1e-5 and terminal<1e-5))
    info['gains']=tracking_gains(plant,info) if info['success'] and compute_gains else []
    return info


if __name__=='__main__':
    import argparse,json
    parser=argparse.ArgumentParser();parser.add_argument('--order',type=int,default=3);parser.add_argument('--duration',type=float,default=5)
    parser.add_argument('--nodes',type=int,default=201);parser.add_argument('--guess');parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args();p=Plant(Parameters(n=args.order));s=np.zeros(p.dim);s[1:p.d]=np.pi
    guess=json.loads(Path(args.guess).read_text()) if args.guess else None
    out=optimize(p,s,args.duration,args.nodes,guess,seed=args.seed)
    Path(f'results/optimal-{args.order}.json').write_text(json.dumps(out),encoding='utf8')
    from .validate_plan import replay
    report=replay(p,out,total=args.duration+10);report.pop('history')
    Path(f'results/optimal-{args.order}-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in out.items() if k not in ['states','forces','gains','derivatives']},indent=2));print(report)
