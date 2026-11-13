"""Implicit inverse-dynamics collocation: passive joint forces constrained to zero.

This is an alternative offline transcription; it adds no physical actuator.
The exported input remains a single bounded cart force.
"""
import time
import numpy as np
from .optimal import ca
from .model import wrap
from .planner import tracking_gains

def inverse_function(plant):
    n=plant.n;d=plant.d;p=plant.p
    s=ca.MX.sym('s',plant.dim);acc=ca.MX.sym('acc',d)
    theta=s[1:d];v=s[d:];omega=v[1:];a=ca.DM(plant.a)
    coupling=a*ca.cos(theta)
    angular=ca.DM(plant.H)*ca.cos(ca.repmat(theta,1,n)-ca.repmat(theta.T,n,1))
    matrix=ca.vertcat(ca.horzcat(plant.args[2],coupling.T),ca.horzcat(coupling,angular))
    centrifugal=ca.mtimes(ca.DM(plant.H)*ca.sin(ca.repmat(theta,1,n)-ca.repmat(theta.T,n,1)),omega*omega)
    D=np.zeros((n,n));D[0,0]=p.damping
    for i in range(1,n):
        D[i,i]+=p.damping;D[i-1,i-1]+=p.damping;D[i,i-1]-=p.damping;D[i-1,i]-=p.damping
    bias0=p.cart_damping*v[0]-ca.dot(a*ca.sin(theta),omega*omega)
    bias=centrifugal-p.gravity*a*ca.sin(theta)+ca.mtimes(ca.DM(D),omega)
    required=ca.mtimes(matrix,acc)+ca.vertcat(bias0,bias)
    return ca.Function('required_forces',[s,acc],[required])

def optimize(plant,initial,duration=8,nodes=201,guess=None,max_iter=600,seed=42,cancel=None,max_seconds=60,progress=None,target_angles=None,compute_gains=True,endpoint_angles=None,initial_force=None,residual_homotopy=False,force_rate=None,force_fraction=.66,reference_weight=0.):
    if not 0<force_fraction<=1:raise ValueError('Force fraction must remain inside the physical actuator limit')
    start=time.perf_counter();m=plant.dim;d=plant.d;h=duration/(nodes-1)
    initial=np.array(initial);goal=np.zeros(plant.n) if target_angles is None else np.asarray(target_angles)
    target=np.zeros(m);target[1:d]=initial[1:d]-wrap(initial[1:d]-goal)
    if endpoint_angles is not None:target[1:d]=endpoint_angles
    f=inverse_function(plant);opti=ca.Opti();X=opti.variable(m,nodes);A=opti.variable(d,nodes);Am=opti.variable(d,nodes-1)
    derivative=ca.vertcat(X[d:,:],A)
    mid=(X[:,:-1]+X[:,1:])/2+h/8*(derivative[:,:-1]-derivative[:,1:])
    defect=X[:,1:]-X[:,:-1]-h/6*(derivative[:,:-1]+4*ca.vertcat(mid[d:,:],Am)+derivative[:,1:])
    required=f.map(nodes)(X,A);mid_required=f.map(nodes-1)(mid,Am)
    opti.subject_to(defect==0)
    relaxation=None
    if residual_homotopy:
        # A numerical feasibility continuation, not an actuator: intermediate
        # iterates are never exported as solutions. Final residual bound is zero.
        relaxation=opti.parameter()
        scale=ca.DM(plant.a*plant.p.gravity)
        rn=required[1:,:]/ca.repmat(scale,1,nodes)
        rm=mid_required[1:,:]/ca.repmat(scale,1,nodes-1)
        opti.subject_to(opti.bounded(-relaxation,rn,relaxation))
        opti.subject_to(opti.bounded(-relaxation,rm,relaxation))
    else:
        opti.subject_to(required[1:,:]==0);opti.subject_to(mid_required[1:,:]==0)
    U=required[0,:];Um=mid_required[0,:]
    opti.subject_to(Um==(U[:,:-1]+U[:,1:])/2)
    opti.subject_to(X[:,0]==initial);opti.subject_to(X[:,-1]==target)
    opti.subject_to(opti.bounded(-plant.p.rail*.82,X[0,:],plant.p.rail*.82))
    opti.subject_to(opti.bounded(-plant.p.rail*.84,mid[0,:],plant.p.rail*.84))
    opti.subject_to(opti.bounded(-plant.p.max_force*force_fraction,U,plant.p.max_force*force_fraction))
    opti.subject_to(opti.bounded(-plant.p.max_force*force_fraction,Um,plant.p.max_force*force_fraction))
    opti.subject_to(U[0,-1]==0)
    if initial_force is not None:opti.subject_to(U[0,0]==initial_force)
    if force_rate is not None:opti.subject_to(opti.bounded(-force_rate*h,U[:,1:]-U[:,:-1],force_rate*h))
    objective=h*(.001*ca.sumsqr(U)+.01*ca.sumsqr(X[0,:]))+.0002*ca.sumsqr(U[:,1:]-U[:,:-1])+h*1e-8*ca.sumsqr(A)
    if relaxation is not None:objective+=h*200*(ca.sumsqr(rn)+ca.sumsqr(rm))
    opti.minimize(objective)
    t=np.linspace(0,1,nodes);blend=3*t*t-2*t*t*t
    z=initial[None,:]+blend[:,None]*(target-initial)
    z[:,d:]=6*(t-t*t)[:,None]/duration*(target-initial)[None,:d]
    z[:,0]=.5*np.sin(2*np.pi*t)*np.sin(np.pi*t)
    if guess is not None:
        old=np.linspace(0,1,len(guess['states']));oldx=np.array(guess['states'])
        for j in range(m):z[:,j]=np.interp(t,old,oldx[:,j])
        z[:,d:]*=guess['duration']/duration
        correction=target[:d]-z[-1,:d];z[:,:d]+=blend[:,None]*correction
        z[:,d:]+=(6*t*(1-t)/duration)[:,None]*correction
    elif seed!=42:
        z[:,1:d]+=.1*np.sin(np.pi*t)[:,None]*np.random.default_rng(seed).normal(size=plant.n)
    acc=np.gradient(z[:,d:],h,axis=0)
    middle_acc=(acc[:-1]+acc[1:])/2
    if guess is not None and len(guess.get('forces',[]))==len(guess['states']):
        # A dynamics-consistent warm start preserves a feasible refined input.
        # Finite differences of velocity can destroy feasibility at fast turns.
        warm_force=np.interp(t,old,np.asarray(guess['forces']))
        derivative=plant.batch(z.copy(),warm_force.copy());acc=derivative[:,d:]
        mid_state=(z[:-1]+z[1:])/2+h/8*(derivative[:-1]-derivative[1:])
        middle_acc=plant.batch(mid_state.copy(),((warm_force[:-1]+warm_force[1:])/2).copy())[:,d:]
    opti.set_initial(X,z.T);opti.set_initial(A,acc.T);opti.set_initial(Am,middle_acc.T)
    if reference_weight:
        if guess is None or reference_weight<0:raise ValueError('Reference projection requires a warm input and positive weight')
        opti.minimize(objective+reference_weight*ca.sumsqr(X-ca.DM(z.T)))
    best=None;iterations=0
    def callback(i):
        nonlocal best,iterations
        iterations=i
        if cancel is not None and cancel.is_set():raise InterruptedError('已取消离线计算')
        if time.perf_counter()-start>max_seconds:raise TimeoutError('本次离线搜索达到预算')
        if progress and i%10==0:progress(i)
        if i%10==0 and i>0:
            error=max(float(np.max(abs(np.asarray(opti.debug.value(defect))))),float(np.max(abs(np.asarray(opti.debug.value(required[1:,:]))))),float(np.max(abs(np.asarray(opti.debug.value(mid_required[1:,:]))))))
            terminal=float(np.linalg.norm(np.asarray(opti.debug.value(X[:,-1])).ravel()-target))
            if error<1e-8 and terminal<1e-8:best=(np.asarray(opti.debug.value(X)).T,np.asarray(opti.debug.value(U)).reshape(-1))
    opti.callback(callback)
    opti.solver('ipopt',{'print_time':False},{'print_level':0,'sb':'yes','max_iter':max_iter,'max_cpu_time':max_seconds,'tol':1e-8,'acceptable_tol':1e-5,'mu_strategy':'adaptive'})
    try:
        for allowed in ([2.,.2,.02,0.] if residual_homotopy else [0.]):
            if relaxation is not None:opti.set_value(relaxation,allowed)
            sol=opti.solve()
            if allowed!=0.:opti.set_initial(opti.x,sol.value(opti.x))
        states=np.asarray(sol.value(X)).T;forces=np.asarray(sol.value(U)).reshape(-1)
    except RuntimeError:
        if cancel is not None and cancel.is_set():raise InterruptedError()
        if best is not None:states,forces=best
        else:states=np.asarray(opti.debug.value(X)).T;forces=np.asarray(opti.debug.value(U)).reshape(-1)
    derivatives=plant.batch(states.copy(),forces.copy())
    middle=(states[:-1]+states[1:])/2+h/8*(derivatives[:-1]-derivatives[1:])
    fm=plant.batch(middle.copy(),((forces[:-1]+forces[1:])/2).copy())
    actual_defect=float(np.max(abs(states[1:]-states[:-1]-h/6*(derivatives[:-1]+4*fm+derivatives[1:]))))
    terminal=float(np.linalg.norm(states[-1]-target))
    info=dict(initial=initial.tolist(),target_angles=goal.tolist(),duration=duration,dt=h,states=states.tolist(),forces=forces.tolist(),derivatives=derivatives.tolist(),
        defect=actual_defect,terminal_error=terminal,nfev=iterations,wall_seconds=time.perf_counter()-start,
        solver='IPOPT / implicit passive-joint collocation',success=bool(actual_defect<1e-5 and terminal<1e-5))
    info['gains']=tracking_gains(plant,info) if info['success'] and compute_gains else []
    return info
