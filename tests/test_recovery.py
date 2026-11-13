import json
import subprocess
import numpy as np
import pytest
from triple_pendulum.model import Plant,Parameters
from triple_pendulum.control import analyze
from triple_pendulum.recovery import dissipative_force,recover_plan

def test_near_upright_recovery_enforces_cart_force_slew():
    plant=Plant(Parameters(n=1));initial=np.array([0.,.021,0.,0.])
    plan,_=recover_plan(plant,initial,[0.])
    assert plan['force_rate']==500
    assert plan['strict_rest']
    assert plan['verification']['max_force_rate']<=500+1e-6


@pytest.mark.parametrize('n',[1,3,5])
def test_cart_dissipation_removes_mechanical_energy_without_joint_actuators(n):
    p=Plant(Parameters(n=n));rng=np.random.default_rng(n)
    for _ in range(5):
        state=rng.normal(size=p.dim);kx=8.;kv=6.
        u=dissipative_force(state,1.,p.p.rail,p.p.max_force,kx,kv,0.)
        direction=p.rhs(state,u);eps=1e-6
        energy_dot=(p.energy(state+eps*direction)-p.energy(state-eps*direction))/(2*eps)
        x=state[0];spring=.4*p.p.max_force
        potential_gradient=spring*np.tanh(kx*(x+.5*x**3/p.p.rail**2)/spring)
        assert energy_dot+potential_gradient*state[p.d]<=1e-5
        assert abs(u)<=p.p.max_force


def test_real_worker_recovers_arbitrary_positions_and_angular_velocities(tmp_path):
    from triple_pendulum import transitions,repository
    fixtures={'plans':[],'forces':[]}
    for n in range(1,6):
        p=Plant(Parameters(n=n));rng=np.random.default_rng(720+n)
        x=np.zeros(p.dim);x[0]=.3;x[1:p.d]=rng.uniform(-np.pi,np.pi,n);x[p.d:]=rng.uniform(-.8,.8,p.d)
        available=[r for r in transitions.catalog(n)['entries'] if r['status']=='ready' and r['source']=='D'*n]
        goal=np.array(repository.angles(next((r['target'] for r in available if r['target']=='U'*n),available[0]['target'])))
        original=x.copy();result=recover_plan(p,x,goal);assert result is not None,f'{n}-link recovery did not pass physical validation'
        plan,_=result
        np.testing.assert_array_equal(x,original);np.testing.assert_array_equal(plan['initial'],original)
        assert plan['verification']['final_stable']
        assert plan['verification']['max_force_rate']<=500+1e-6
        fixtures['plans'].append(dict(design=analyze(p,target=goal),plan=plan))
        for t in (0.,.1,.35,.6,1.):
            policy=dict(kx=8.,kv=6.,kick=12.)
            fixtures['forces'].append(dict(state=x.tolist(),time=t,parameters=p.p.dict(),policy=policy,
                force=dissipative_force(x,t,p.p.rail,p.p.max_force,8.,6.,12.)))
    path=tmp_path/'recovery.json';path.write_text(json.dumps(fixtures),encoding='utf8')
    result=subprocess.run(['node','tests/check-recovery.mjs',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_long_recovery_keeps_the_original_initial_state_in_saved_replay(tmp_path):
    from triple_pendulum import precomputed
    p=Plant(Parameters(n=1));initial=precomputed.hanging(p);leaf=precomputed.lookup(p,initial,[0])
    plan=dict(initial=initial.tolist(),target_angles=[0.],duration=65+leaf['duration'],wall_seconds=0.,success=True,
        segments=[dict(kind='dissipate',duration=65.,policy=dict(kx=8.,kv=6.,kick=0.)),dict(kind='track',duration=leaf['duration'],plan=leaf)])
    path=tmp_path/'long.json';path.write_text(json.dumps(dict(forces=[],plans=[dict(design=analyze(p,target=[0]),plan=plan)])),encoding='utf8')
    result=subprocess.run(['node','tests/check-recovery.mjs',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_custom_recovery_is_loaded_directly_after_success(tmp_path,monkeypatch):
    from triple_pendulum import repository,planning_service
    p=Plant(Parameters(n=1));initial=np.array([.3,.2,0.,.1]);plan,history=recover_plan(p,initial,[0.])
    monkeypatch.setattr(repository,'ROOT',tmp_path/'saved')
    repository.store(plan,p,history)
    def forbidden(*args,**kwargs):raise AssertionError('An exact saved recovery must not restart a search')
    monkeypatch.setattr('triple_pendulum.recovery.recover_plan',forbidden)
    result=planning_service.certified_plan(p,initial,3,42)
    assert result['success'] and result['wall_seconds']==0
    np.testing.assert_array_equal(result['initial'],initial)


def test_external_pulse_finishes_before_replanning_and_is_cleared_on_reset(tmp_path):
    path=tmp_path/'design.json';path.write_text(json.dumps(analyze(Plant(),target=[0.]*3)),encoding='utf8')
    result=subprocess.run(['node','tests/check-disturbance.mjs',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
