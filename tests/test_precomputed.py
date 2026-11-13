import json
import subprocess
from itertools import product
import numpy as np
import pytest
from triple_pendulum.model import Plant,Parameters
from triple_pendulum.control import analyze,lqr
from triple_pendulum import precomputed,repository

@pytest.mark.parametrize('n',[1,2,3,4,5])
def test_all_equilibrium_options(n):
    options=repository.patterns(n)
    assert len(options)==2**n-1
    assert len(set(options))==len(options)
    assert 'D'*n not in options
    plant=Plant(Parameters(n=n))
    for code in options:
        goal=repository.angles(code);A,B=plant.linearize(goal);K=lqr(plant,target=goal)[0]
        assert np.linalg.eigvals(A-B@K).real.max()<-.1

def test_manifest_tracks_57_distinct_hanging_tasks():
    bank=precomputed.catalog()
    assert bank['total']==57
    assert {(r['order'],r['pattern']) for r in bank['entries']}=={(n,code) for n in range(1,6) for code in repository.patterns(n)}

def test_runtime_uses_preoptimized_file_without_verification_or_optimizer(monkeypatch):
    from copy import deepcopy
    from triple_pendulum import planning_service,server,transitions
    plant=Plant(Parameters(n=1));initial=precomputed.hanging(plant)
    # Only a rate-certified cache entry may bypass the strengthened verifier.
    certified=transitions.lookup(plant,'D','U')
    assert certified['force_rate']==500 and certified['verification']['max_force_rate']<=500+1e-6
    certified.update(precomputed=True,wall_seconds=0.)
    monkeypatch.setattr(precomputed,'lookup',lambda *a,**k:deepcopy(certified))
    def forbidden(*a,**k):raise AssertionError('Live startup attempted to optimize or re-integrate the cached plan')
    monkeypatch.setattr(planning_service,'verify',forbidden)
    result=planning_service.certified_plan(plant,initial,3,42)
    assert result['precomputed'] and result['wall_seconds']==0
    info=server.design({'parameters':plant.p.dict(),'initial':initial.tolist(),'pattern':'U'})
    assert info['hanging_plan']['precomputed']


def test_legacy_precomputed_plan_is_reverified_before_reuse(monkeypatch):
    from copy import deepcopy
    from triple_pendulum import planning_service,transitions
    plant=Plant(Parameters(n=1));initial=precomputed.hanging(plant)
    legacy=transitions.lookup(plant,'D','U');legacy.pop('force_rate')
    monkeypatch.setattr(precomputed,'lookup',lambda *a,**k:deepcopy(legacy))
    original_verify=planning_service.verify;calls=[]
    def observed_verify(*args,**kwargs):
        calls.append(True)
        return original_verify(*args,**kwargs)
    monkeypatch.setattr(planning_service,'verify',observed_verify)
    result=planning_service.certified_plan(plant,initial,3,42)
    assert calls==[True] and result['force_rate']==500
    assert result['verification']['final_stable']
    assert result['verification']['max_force_rate']<=500+1e-6

def test_incompatible_initial_or_parameters_do_not_use_default_bank():
    p=Plant(Parameters(n=1));x=precomputed.hanging(p);x[-1]=.1
    assert precomputed.lookup(p,x,[0]) is None
    p=Plant(Parameters(n=1,length=.8))
    assert precomputed.lookup(p,precomputed.hanging(p),[0]) is None


def test_concatenated_reference_preserves_physical_state_and_force():
    from triple_pendulum.precompute_transitions import concatenate
    from triple_pendulum.validate_plan import replay
    p=Plant(Parameters(n=3));prefix=precomputed.lookup(p,precomputed.hanging(p),[0]*3)
    endpoint=np.asarray(prefix['states'][-1]);force=float(prefix['forces'][-1])
    nodes=round(1/prefix['dt'])+1
    suffix=dict(duration=1.,dt=prefix['dt'],states=np.tile(endpoint,(nodes,1)).tolist(),forces=[force]*nodes,
        derivatives=[p.rhs(endpoint,force).tolist()]*nodes,target_angles=[0.]*3)
    combined=concatenate(p,prefix,suffix)
    np.testing.assert_allclose(combined['initial'],precomputed.hanging(p),atol=1e-12)
    np.testing.assert_allclose(combined['states'][0],prefix['states'][0],atol=1e-12)
    np.testing.assert_allclose(combined['states'][round(prefix['duration']/combined['dt'])],endpoint,atol=1e-10)
    assert combined['success']
    result=replay(p,combined,total=combined['duration']+5)
    assert result['final_stable'] and result['max_cart']<p.p.rail

def test_actual_worker_starts_precomputed_physics_without_planning(tmp_path):
    fixtures=[]
    # All five upright cases plus every currently ready mixed case.
    for row in precomputed.catalog()['entries']:
        if row['status']!='ready':continue
        p=Plant(Parameters(**row['parameters']));goal=repository.angles(row['pattern'])
        plan=precomputed.lookup(p,precomputed.hanging(p),goal)
        fixtures.append(dict(design=analyze(p,target=goal),plan=plan))
    path=tmp_path/'precomputed.json';path.write_text(json.dumps(fixtures),encoding='utf8')
    result=subprocess.run(['node','tests/check-precomputed.mjs',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

@pytest.mark.parametrize('n',[1,3,4,5])
def test_implicit_collocation_requires_zero_control_torque_at_all_joints(n):
    from triple_pendulum.implicit_optimal import inverse_function
    p=Plant(Parameters(n=n));state=np.random.default_rng(n).normal(size=p.dim)*.4
    acceleration=p.rhs(state,17.5)[p.d:]
    forces=np.array(inverse_function(p)(state,acceleration)).ravel()
    np.testing.assert_allclose(forces,np.r_[17.5,np.zeros(n)],atol=2e-11)


def test_implicit_solver_completes_a_real_hanging_swingup():
    from triple_pendulum.implicit_optimal import optimize
    p=Plant(Parameters(n=1));initial=precomputed.hanging(p)
    result=optimize(p,initial,duration=3,nodes=81,max_seconds=30,compute_gains=False)
    assert result['success'] and result['defect']<1e-7
    np.testing.assert_allclose(result['states'][0],initial,atol=1e-8)
    assert np.linalg.norm(np.asarray(result['states'][-1])[[0,2,3]])<1e-7
    assert abs(np.sin(result['states'][-1][1]/2))<1e-7
    assert np.asarray(result['forces']).shape==(81,)
    assert np.max(abs(np.asarray(result['forces'])))<=p.p.max_force*.66+1e-6
