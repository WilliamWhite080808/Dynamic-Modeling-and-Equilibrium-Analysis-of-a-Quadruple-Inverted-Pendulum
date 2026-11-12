import json
import subprocess
from pathlib import Path
import numpy as np
import pytest
from scipy.integrate import solve_ivp
from triple_pendulum.model import Plant,Parameters,wrap
from triple_pendulum.control import lqr,analyze,sensor_matrix,Observer,measurement
from triple_pendulum.simulation import simulate

@pytest.mark.parametrize('n',[1,2,3,4,5,10])
def test_dimensions_spd_and_equilibria(n):
    p=Plant(Parameters(n=n));rng=np.random.default_rng(20)
    for _ in range(4):
        q=rng.normal(size=p.d);M=p.mass_matrix(q)
        np.testing.assert_allclose(M,M.T,atol=1e-14)
        assert np.linalg.eigvalsh(M).min()>1e-5
    for angle in (0,np.pi):
        s=np.zeros(p.dim);s[1:p.d]=angle
        np.testing.assert_allclose(p.rhs(s),0,atol=2e-12)
    A,B=p.linearize();assert A.shape==(p.dim,p.dim);assert B.shape==(p.dim,1)
    for mode in ('full_state','angles_only','cart_and_tip','cart_only'):
        C=sensor_matrix(p,mode);assert C.shape[1]==p.dim
        assert len(measurement(p,np.zeros(p.dim),mode))==len(C)

@pytest.mark.parametrize('n',[1,2,3,4,5])
def test_only_cart_is_actuated(n):
    """No control torque, hidden motors or directly corrected joint states."""
    p=Plant(Parameters(n=n));s=np.random.default_rng(n).normal(size=p.dim)
    force=p.mass_matrix(s[:p.d])@(p.rhs(s,12)[p.d:]-p.rhs(s,0)[p.d:])
    np.testing.assert_allclose(force,np.r_[12,np.zeros(n)],rtol=1e-12,atol=2e-12)

@pytest.mark.parametrize('n',[1,2,3,5])
def test_analytic_linearization(n):
    p=Plant(Parameters(n=n));A,B=p.linearize();eps=1e-6;I=np.eye(p.dim)
    numerical=np.column_stack([(p.rhs(eps*i)-p.rhs(-eps*i))/(2*eps) for i in I])
    np.testing.assert_allclose(A,numerical,rtol=2e-9,atol=2e-8)
    np.testing.assert_allclose(B[:,0],(p.rhs(np.zeros(p.dim),eps)-p.rhs(np.zeros(p.dim),-eps))/(2*eps),rtol=1e-12)

@pytest.mark.parametrize('n',[1,2,3])
def test_lagrange_independent_finite_difference(n):
    # Verify M and centrifugal force directly from kinetic energy using geometry Jacobians.
    p=Plant(Parameters(n=n,damping=0,cart_damping=0));rng=np.random.default_rng(n)
    q=rng.normal(size=p.d);v=rng.normal(size=p.d);eps=1e-5
    def geometric_mass(q):
        M=np.zeros((p.d,p.d));M[0,0]=p.p.cart_mass
        for i in range(n):
            J=np.zeros((2,p.d));J[0,0]=1
            for j in range(i+1):
                l=p.centers[i] if j==i else p.lengths[j]
                J[:,j+1]=[l*np.cos(q[j+1]),-l*np.sin(q[j+1])]
            M+=p.masses[i]*(J.T@J);M[i+1,i+1]+=p.inertia[i]
        return M
    M=geometric_mass(q);np.testing.assert_allclose(M,p.mass_matrix(q),atol=1e-14)
    D=np.array([(geometric_mass(q+eps*e)-geometric_mass(q-eps*e))/(2*eps) for e in np.eye(p.d)])
    bias=np.array([sum((D[k,i,j]+D[j,i,k]-D[i,j,k])*v[j]*v[k]/2 for j in range(p.d) for k in range(p.d)) for i in range(p.d)])
    G=np.r_[0,-p.p.gravity*p.a*np.sin(q[1:])]
    s=np.r_[q,v];np.testing.assert_allclose(M@p.rhs(s)[p.d:]+bias+G,0,atol=2e-8)

def test_energy_conservation_reference():
    p=Plant(Parameters(damping=0,cart_damping=0));s=np.array([0.,.4,-.3,.2,0.,.2,-.1,.4])
    sol=solve_ivp(lambda t,x:p.rhs(x),(0,3),s,method='DOP853',rtol=1e-11,atol=1e-13,max_step=.01)
    energy=np.array([p.energy(x) for x in sol.y.T]);assert max(abs(energy-energy[0]))<2e-8

@pytest.mark.parametrize('n',[1,2,3,4,5])
def test_lqr_stable_and_cart_only_observable(n):
    p=Plant(Parameters(n=n));K,P,_,_=lqr(p);A,B=p.linearize()
    assert K.shape==(1,p.dim);assert P.shape==(p.dim,p.dim)
    assert np.linalg.eigvals(A-B@K).real.max()<-.2
    report=analyze(p,'cart_only')
    assert report['controllability']['rank']==p.dim
    # Report numerical degradation without claiming a rank when conditioning loses it.
    assert report['observability']['sigma_min']>0

@pytest.mark.parametrize('n',[1,2,3,4,5])
def test_nonlinear_local_recovery(n):
    _,report=simulate(Parameters(n=n),duration=12)
    assert report['final_stable']
    assert report['final_angle_deg']<.01
    assert report['max_cart']<.3
    assert report['max_force']<=120

def test_reference_agrees_and_reproducible():
    p=Parameters();a,_=simulate(p,duration=1);b,_=simulate(p,duration=1,reference=True)
    np.testing.assert_allclose(a[:,:9],b[:,:9],rtol=1e-6,atol=2e-7)
    again,_=simulate(p,duration=1)
    np.testing.assert_array_equal(a,again)

def test_observer_measurement_only_and_joseph_covariance():
    p=Plant(Parameters(n=2));o=Observer(p,'cart_and_tip','ekf');truth=np.zeros(p.dim);truth[1:3]=.002
    for _ in range(100):
        truth=p.rk4(truth,0,.004)
        o.update(measurement(p,truth,'cart_and_tip'),0,.004)
        np.testing.assert_allclose(o.P,o.P.T,atol=1e-12)
        assert np.linalg.eigvalsh(o.P).min()>-1e-12
    # The update accepts measurements and applied input only, no truth-state handle.
    import inspect
    assert list(inspect.signature(o.update).parameters)==['y','u','dt','noise']
    assert np.linalg.norm(o.x-truth)<.02

def test_single_rod_known_formula():
    p=Plant(Parameters(n=1,damping=0,cart_damping=0));s=np.array([.1,.3,.2,-.4]);M=p.mass_matrix(s[:2])
    l=p.lengths[0];m=p.masses[0]
    expected=np.array([[p.p.cart_mass+m,m*l/2*np.cos(.3)],[m*l/2*np.cos(.3),m*l*l/3]])
    np.testing.assert_allclose(M,expected,atol=1e-14)

def test_javascript_python_parity(tmp_path):
    fixture=[]
    for n in range(1,6):
        p=Plant(Parameters(n=n));s=np.random.default_rng(n).normal(size=p.dim)*.3
        fixture.append(dict(design=analyze(p,'cart_and_tip'),s=s.tolist(),rhs=p.rhs(s,7.0).tolist(),step=p.rk4(s,7.,.001).tolist()))
    path=tmp_path/'fixtures.json';path.write_text(json.dumps(fixture),encoding='utf8')
    result=subprocess.run(['node','tests/check-physics.mjs',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

def test_all_five_swingups_in_browser_physics(tmp_path):
    designs=[analyze(Plant(Parameters(n=n))) for n in range(1,6)]
    path=tmp_path/'designs.json';path.write_text(json.dumps(designs),encoding='utf8')
    result=subprocess.run(['node','tests/check-swingup.mjs',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
