"""Online direct collocation: only a force plan; never writes physical states.

Hermite-Simpson defects, sparse numerical Jacobian, bounded cart and force.
Plans are tracked against the live integrated state with a time-varying LQR.
"""
import json
import time
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.linalg import solve_discrete_are
from .model import Plant, Parameters, wrap
from .control import lqr


def plan(plant,initial,duration=5.0,nodes=81,max_nfev=350,seed=1,progress=None,guess=None):
    start=time.perf_counter(); m=plant.dim; h=duration/(nodes-1); width=m+1
    initial=np.asarray(initial).copy()
    # Unwrapped target: choose the closest upward winding, retaining actual state.
    target=np.zeros(m); target[1:plant.d]=initial[1:plant.d]-wrap(initial[1:plant.d])
    diff=target-initial
    z=np.zeros((nodes,width))
    t=np.linspace(0,1,nodes)
    z[:,:m]=initial[None,:]+(3*t*t-2*t*t*t)[:,None]*diff[None,:]
    z[:,plant.d:m]=6*(t-t*t)[:,None]/duration*diff[None,:plant.d]
    rng=np.random.default_rng(seed)
    z[:,0]=0.5*np.sin(2*np.pi*t)*np.sin(np.pi*t)
    z[:,m]=10*np.sin(4*np.pi*t)
    if guess is not None:
        old=np.linspace(0,1,len(guess['states']))
        for j in range(m): z[:,j]=np.interp(t,old,np.array(guess['states'])[:,j])
        z[:,m]=np.interp(t,old,guess['forces'])
    # Defects are scaled relative to force regularization; final solution verified independently.
    def residual(flat):
        z=flat.reshape(nodes,width); X=z[:,:m]; U=z[:,m]
        f=plant.batch(X.copy(),U.copy())
        mid=(X[:-1]+X[1:])/2+h/8*(f[:-1]-f[1:])
        fm=plant.batch(mid.copy(),((U[:-1]+U[1:])/2).copy())
        defects=(X[1:]-X[:-1]-h/6*(f[:-1]+4*fm+f[1:]))
        return np.concatenate((defects.ravel()*30,(X[0]-initial)*100,(X[-1]-target)*100,U*0.0005,X[:,0]*0.0005))
    rows=(nodes-1)*m+2*m+2*nodes
    sp=lil_matrix((rows,nodes*width),dtype=int)
    for k in range(nodes-1): sp[k*m:(k+1)*m,k*width:(k+2)*width]=1
    o=(nodes-1)*m
    sp[o:o+m,:m]=np.eye(m); sp[o+m:o+2*m,(nodes-1)*width:(nodes-1)*width+m]=np.eye(m)
    for k in range(nodes): sp[o+2*m+k,k*width+m]=1; sp[o+2*m+nodes+k,k*width]=1
    low=np.full_like(z,-np.inf); high=np.full_like(z,np.inf)
    low[:,0]=-plant.p.rail*0.82; high[:,0]=plant.p.rail*0.82
    # Reserve one third of the actuator for feedback corrections, not just feedforward.
    low[:,m]=-plant.p.max_force*0.66; high[:,m]=plant.p.max_force*0.66
    z=np.maximum(np.minimum(z,high-1e-6),low+1e-6)
    result=least_squares(residual,z.ravel(),jac_sparsity=sp.tocsr(),bounds=(low.ravel(),high.ravel()),
                         max_nfev=max_nfev,ftol=2e-7,xtol=2e-7,gtol=1e-7,verbose=0)
    z=result.x.reshape(nodes,width)
    defects=residual(result.x)[:(nodes-1)*m]/30
    terminal=float(np.linalg.norm(z[-1,:m]-target))
    info=dict(duration=duration,dt=h,states=z[:,:m].tolist(),forces=z[:,m].tolist(),
              defect=float(np.max(abs(defects))),terminal_error=terminal,
              wall_seconds=time.perf_counter()-start,nfev=result.nfev,initial=initial.tolist(),
              success=bool(np.max(abs(defects))<0.003 and terminal<0.03))
    info['derivatives']=plant.batch(z[:,:m].copy(),z[:,m].copy()).tolist()
    info['gains']=tracking_gains(plant,info)
    return info


def densify_reference(plant,info,spacing=.005):
    """Resolve fast nonlinear changes before computing a feedback schedule."""
    from copy import deepcopy
    result=deepcopy(info);states=np.asarray(info['states']);forces=np.asarray(info['forces'])
    derivatives=np.asarray(info.get('derivatives',plant.batch(states.copy(),forces.copy())))
    nodes=int(np.ceil(info['duration']/spacing))+1
    t=np.linspace(0,info['duration'],nodes);z=np.minimum(t/info['dt'],len(states)-1)
    j=np.minimum(z.astype(int),len(states)-2);a=(z-j)[:,None];h=info['dt']
    dense=(2*a**3-3*a*a+1)*states[j]+(a**3-2*a*a+a)*h*derivatives[j]+(-2*a**3+3*a*a)*states[j+1]+(a**3-a*a)*h*derivatives[j+1]
    u=(1-a[:,0])*forces[j]+a[:,0]*forces[j+1]
    dt=info['duration']/(nodes-1);f=plant.batch(dense.copy(),u.copy())
    mid=(dense[:-1]+dense[1:])/2+dt/8*(f[:-1]-f[1:])
    fm=plant.batch(mid.copy(),((u[:-1]+u[1:])/2).copy())
    defect=float(np.max(abs(dense[1:]-dense[:-1]-dt/6*(f[:-1]+4*fm+f[1:]))))
    result.update(dt=dt,states=dense.tolist(),forces=u.tolist(),defect=defect,
        derivatives=f.tolist(),gains=[])
    return result


def tracking_gains(plant,info):
    z=np.column_stack((info['states'],info['forces'])); nodes=len(z); h=info['dt']; m=plant.dim
    K,P,Q,R=lqr(plant,target=info.get('target_angles')); eps=1e-5; identity=np.eye(m)
    As=[];Bs=[]
    for row in z:
        x=row[:m].copy();u=row[m]
        As.append(np.column_stack([(plant.rhs(x+eps*identity[j],u)-plant.rhs(x-eps*identity[j],u))/(2*eps) for j in range(m)]))
        Bs.append(((plant.rhs(x,u+eps)-plant.rhs(x,u-eps))/(2*eps))[:,None])
    # Integrate backwards over the actual interval [k,k+1], with interpolated
    # linearizations. The terminal policy must equal the upright CARE controller.
    gains=np.zeros((nodes,m));gains[-1]=K[0]
    pieces=max(1,int(np.ceil(h/.001)));delta=h/pieces
    for k in range(nodes-2,-1,-1):
        for j in range(pieces):
            alpha=1-(j+.5)/pieces
            A=(1-alpha)*As[k]+alpha*As[k+1];B=(1-alpha)*Bs[k]+alpha*Bs[k+1]
            F=np.linalg.solve(identity-delta*A/2,identity+delta*A/2)
            G=np.linalg.solve(identity-delta*A/2,B*delta)
            gain=np.linalg.solve(R*delta+G.T@P@G,G.T@P@F)
            P=Q*delta+F.T@P@(F-G@gain);P=(P+P.T)/2
        gains[k]=(Bs[k].T@P/R[0,0])[0]
    return gains.tolist()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--order',type=int,default=3); parser.add_argument('--duration',type=float,default=5)
    parser.add_argument('--nodes',type=int,default=81); parser.add_argument('--iterations',type=int,default=500)
    args=parser.parse_args(); p=Plant(Parameters(n=args.order)); x=np.zeros(p.dim); x[1:p.d]=np.pi
    out=plan(p,x,args.duration,args.nodes,args.iterations)
    path=Path('results')/f'swingup-{args.order}.json';path.write_text(json.dumps(out),encoding='utf8')
    print(json.dumps({k:v for k,v in out.items() if k not in ('states','forces','gains','derivatives')},indent=2))
