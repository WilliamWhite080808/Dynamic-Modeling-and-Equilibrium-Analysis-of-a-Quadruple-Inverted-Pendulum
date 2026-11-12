"""Rigid uniform rods; the cart is the only actuator. No state stabilization tricks."""
from dataclasses import dataclass, asdict
import numpy as np
from numba import njit


@dataclass
class Parameters:
    n: int = 3
    cart_mass: float = 1.5
    length: float = 0.65
    mass: float = 0.3
    gravity: float = 9.81
    damping: float = 0.006
    cart_damping: float = 0.08
    max_force: float = 120.0
    rail: float = 2.4
    point_mass: bool = False

    def __post_init__(self):
        if not 1 <= self.n <= 20:
            raise ValueError("Supported numerical orders are 1..20")
        if min(self.cart_mass, self.mass, self.length, self.gravity, self.max_force, self.rail) <= 0:
            raise ValueError("Mass, length, gravity, force and rail must be positive")

    def arrays(self):
        # Slightly taper rods to separate modes and improve numerical conditioning.
        lengths = self.length * np.linspace(1.0, 0.78, self.n) if self.n > 1 else np.array([self.length])
        masses = self.mass * np.linspace(1.0, 0.7, self.n) if self.n > 1 else np.array([self.mass])
        centers = lengths * (1.0 if self.point_mass else 0.5)
        inertia = np.zeros(self.n) if self.point_mass else masses * lengths**2 / 12
        return lengths, masses, centers, inertia

    def dict(self):
        return asdict(self)


@njit(cache=True)
def acceleration(q, v, u, H, a, total_mass, gravity, damping, cart_damping):
    n = len(a)
    M = np.empty((n+1, n+1), dtype=q.dtype)
    rhs = np.zeros(n+1, dtype=q.dtype)
    M[0, 0] = total_mass
    rhs[0] = u - cart_damping*v[0]
    for i in range(n):
        M[0, i+1] = M[i+1, 0] = a[i]*np.cos(q[i+1])
        rhs[0] += a[i]*np.sin(q[i+1])*v[i+1]**2
        rhs[i+1] = gravity*a[i]*np.sin(q[i+1])
        for j in range(n):
            delta = q[i+1]-q[j+1]
            M[i+1, j+1] = H[i, j]*np.cos(delta)
            rhs[i+1] -= H[i, j]*np.sin(delta)*v[j+1]**2
        # Relative angular velocities at passive joints, including rod 1 / cart.
        rhs[i+1] -= damping*(v[i+1] - (v[i] if i else 0.0))
        if i < n-1:
            rhs[i+1] += damping*(v[i+2]-v[i+1])
    return np.linalg.solve(M, rhs)


@njit(cache=True)
def dynamics(s, u, H, a, total_mass, gravity, damping, cart_damping):
    d = len(a)+1
    out = np.empty_like(s)
    out[:d] = s[d:]
    out[d:] = acceleration(s[:d], s[d:], u, H, a, total_mass, gravity, damping, cart_damping)
    return out


@njit(cache=True)
def batch_dynamics(states, forces, H, a, total_mass, gravity, damping, cart_damping):
    out = np.empty_like(states)
    for k in range(len(states)):
        out[k] = dynamics(states[k], forces[k], H, a, total_mass, gravity, damping, cart_damping)
    return out


class Plant:
    def __init__(self, p=None):
        self.p = p or Parameters()
        self.n = self.p.n
        self.d = self.n+1
        self.dim = 2*self.d
        self.lengths, self.masses, self.centers, self.inertia = self.p.arrays()
        distal = np.array([sum(self.masses[i+1:]) for i in range(self.n)])
        self.a = self.masses*self.centers + distal*self.lengths
        self.H = np.empty((self.n, self.n))
        for i in range(self.n):
            for j in range(self.n):
                if i == j:
                    self.H[i,j] = self.masses[i]*self.centers[i]**2 + distal[i]*self.lengths[i]**2 + self.inertia[i]
                else:
                    k,l = min(i,j),max(i,j)
                    self.H[i,j] = self.lengths[k]*self.a[l]
        self.args = (self.H,self.a,self.p.cart_mass+sum(self.masses),self.p.gravity,self.p.damping,self.p.cart_damping)

    def rhs(self, state, u=0.0):
        return dynamics(np.asarray(state),u,*self.args)

    def batch(self, states, forces):
        return batch_dynamics(states,forces,*self.args)

    def mass_matrix(self, q):
        M = np.empty((self.d,self.d))
        M[0,0] = self.args[2]
        M[0,1:] = M[1:,0] = self.a*np.cos(q[1:])
        M[1:,1:] = self.H*np.cos(q[1:,None]-q[None,1:])
        return M

    def energy(self, s):
        return float(0.5*s[self.d:]@self.mass_matrix(s[:self.d])@s[self.d:] + self.p.gravity*self.a@np.cos(s[1:self.d]))

    def linearize(self,target=None):
        angles=np.zeros(self.n) if target is None else np.asarray(target,dtype=float)
        if angles.shape!=(self.n,):raise ValueError('Target must contain N absolute angles')
        M = self.mass_matrix(np.r_[0.,angles])
        G = np.zeros((self.d,self.d)); G[1:,1:] = np.diag(self.p.gravity*self.a*np.cos(angles))
        D = np.zeros_like(G); D[0,0] = self.p.cart_damping
        for i in range(1,self.d):
            D[i,i] += self.p.damping
            if i > 1:
                D[i-1,i-1] += self.p.damping
                D[i,i-1] -= self.p.damping; D[i-1,i] -= self.p.damping
        A = np.zeros((self.dim,self.dim)); A[:self.d,self.d:] = np.eye(self.d)
        A[self.d:,:self.d] = np.linalg.solve(M,G)
        A[self.d:,self.d:] = -np.linalg.solve(M,D)
        B = np.zeros((self.dim,1)); B[self.d:,0] = np.linalg.solve(M,np.eye(self.d)[:,0])
        return A,B

    def rk4(self,s,u,dt):
        k1=self.rhs(s,u); k2=self.rhs(s+dt/2*k1,u)
        k3=self.rhs(s+dt/2*k2,u); k4=self.rhs(s+dt*k3,u)
        return s+dt/6*(k1+2*k2+2*k3+k4)


def wrap(a):
    return (np.asarray(a)+np.pi)%(2*np.pi)-np.pi
