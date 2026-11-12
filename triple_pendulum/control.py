import numpy as np
from scipy.linalg import solve_continuous_are, solve_discrete_are, expm
from scipy.signal import place_poles
from .model import Plant


def lqr(plant, aggressive=1.0,target=None):
    A,B=plant.linearize(target); d=plant.d
    Q=np.diag([10.0]+[300.0*aggressive]*plant.n+[12.0]+[12.0]*plant.n)
    R=np.array([[0.12/aggressive]])
    P=solve_continuous_are(A,B,Q,R)
    K=np.linalg.solve(R,B.T@P)
    return K,P,Q,R


def measurement(plant,s,mode):
    if mode=='full_state': return s.copy()
    if mode=='angles_only': return s[:plant.d].copy()
    if mode=='cart_only': return s[:1].copy()
    return np.array([s[0],s[0]+plant.lengths@np.sin(s[1:plant.d])])


def sensor_matrix(plant,mode,target=None):
    if mode=='full_state': return np.eye(plant.dim)
    if mode=='angles_only': return np.eye(plant.dim)[:plant.d]
    C=np.zeros((1 if mode=='cart_only' else 2,plant.dim)); C[:,0]=1
    if len(C)>1: C[1,1:plant.d]=plant.lengths*(np.cos(target) if target is not None else 1)
    return C


def matrix_health(M):
    sv=np.linalg.svd(M,compute_uv=False)
    tol=sv[0]*max(M.shape)*np.finfo(float).eps
    return dict(rank=int(sum(sv>tol)),sigma_min=float(sv[-1]),condition=float(sv[0]/max(sv[-1],1e-300)))


def analyze(plant,mode='cart_and_tip',aggressive=1.0,target=None):
    A,B=plant.linearize(target); K,P,Q,R=lqr(plant,aggressive,target); C=sensor_matrix(plant,mode,target)
    # Scale powers by fastest open-loop time scale for a useful, declared diagnostic.
    scale=max(abs(np.linalg.eigvals(A)).max(),1.0); F=A/scale
    ctr=np.concatenate([np.linalg.matrix_power(F,i)@B for i in range(plant.dim)],axis=1)
    obs=np.concatenate([C@np.linalg.matrix_power(F,i) for i in range(plant.dim)],axis=0)
    try:
        Po=solve_continuous_are(A.T,C.T,np.eye(plant.dim)*0.05,np.eye(len(C))*0.0001)
        L=Po@C.T/0.0001
    except np.linalg.LinAlgError:
        L=np.zeros((plant.dim,len(C)))
    poles=lambda M:[[float(v.real),float(v.imag)] for v in np.linalg.eigvals(M)]
    return dict(A=A.tolist(),B=B.tolist(),K=K[0].tolist(),P=P.tolist(),Q=np.diag(Q).tolist(),R=float(R[0,0]),C=C.tolist(),L=L.tolist(),
        controllability=matrix_health(ctr),observability=matrix_health(obs),power_scale=float(scale),
        open_poles=poles(A),closed_poles=poles(A-B@K),observer_poles=poles(A-L@C),
        H=plant.H.tolist(),a=plant.a.tolist(),lengths=plant.lengths.tolist(),masses=plant.masses.tolist(),parameters=plant.p.dict(),target_angles=list(target) if target is not None else [0.]*plant.n)


class Observer:
    """Measurement-only interface. Does not receive a Plant simulation state."""
    def __init__(self,model:Plant,mode='cart_and_tip',kind='kalman',initial=None):
        self.model=model; self.mode=mode; self.kind=kind
        self.x=np.zeros(model.dim) if initial is None else initial.copy()
        self.P=np.eye(model.dim)*0.02; self.C=sensor_matrix(model,mode)
        self.A,self.B=model.linearize()
        info=analyze(model,mode); self.L=np.array(info['L'])

    def update(self,y,u,dt,noise=0.002):
        if self.mode=='full_state':
            self.x=y.copy(); return self.x
        if self.kind=='luenberger':
            self.x += dt*(self.A@self.x+self.B[:,0]*u+self.L@(y-self.C@self.x))
            return self.x
        if self.kind=='ekf':
            self.x=self.model.rk4(self.x,u,dt)
            eps=1e-5
            J=np.column_stack([(self.model.rhs(self.x+np.eye(self.model.dim)[i]*eps,u)-self.model.rhs(self.x-np.eye(self.model.dim)[i]*eps,u))/(2*eps) for i in range(self.model.dim)])
            F=np.eye(self.model.dim)+dt*J
            C=self.C.copy()
            if self.mode=='cart_and_tip': C[1,1:self.model.d]=self.model.lengths*np.cos(self.x[1:self.model.d])
            innovation=y-measurement(self.model,self.x,self.mode)
        else:
            F=expm(self.A*dt)
            self.x=F@self.x+np.linalg.solve(np.eye(self.model.dim)-dt*self.A/2,dt*self.B[:,0]*u)
            C=self.C; innovation=y-C@self.x
        P=F@self.P@F.T+np.eye(self.model.dim)*dt*0.01
        R=np.eye(len(y))*max(noise**2,1e-8)
        S=C@P@C.T+R
        gain=np.linalg.solve(S,C@P).T
        self.x+=gain@innovation
        J=np.eye(self.model.dim)-gain@C
        self.P=J@P@J.T+gain@R@gain.T
        self.P=(self.P+self.P.T)/2
        return self.x
