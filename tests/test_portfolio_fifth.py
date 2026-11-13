import importlib.util
from pathlib import Path
import json
import numpy as np
import pytest
from triple_pendulum.portfolio_fifth import METHODS,method_options,accepted,atomic
from triple_pendulum import portfolio_fifth

def test_four_methods_have_distinct_transcriptions_or_constraint_continuation():
    assert len(METHODS)==len(set(METHODS))==4
    assert method_options('residual-continuation')=={'residual_homotopy':True}
    assert method_options('rk4-shooting')=={'transcription':'rk4'}
    with pytest.raises(ValueError):method_options('another-seed')

def test_acceptance_requires_exact_local_physics_and_worker_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr(portfolio_fifth.transitions,'ROOT',tmp_path/'equilibrium_transitions')
    row={'status':'ready','sha256':'current'}
    monkeypatch.setattr(portfolio_fifth.transitions,'case_status',lambda *args:row)
    case=dict(key='5-DDDDD-UUUUU',source='DDDDD',target='UUUUU')
    path=tmp_path/'portfolio/accepted'/(case['key']+'.json')
    assert not accepted(case)
    atomic(path,dict(sha256='old',local_physics_and_worker_accepted=True));assert not accepted(case)
    atomic(path,dict(sha256='current',local_physics_and_worker_accepted=True));assert accepted(case)
    row['status']='retry_pending';assert not accepted(case)

def test_maui_planner_respects_cpu_memory_time_and_hundred_core_limit():
    spec=importlib.util.spec_from_file_location('portfolio_admin',Path(__file__).resolve().parents[1]/'cluster/portfolio_admin.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    text='cu14 100 16384 0 0 INFINITY\ncu15 100 999999 0 0 01:00:00\ncu16 100 999999 0 0 1:00:00:00'
    result=m.allocate(text,25)
    assert len(result)*4==100 and result.count('cu14')<=1 and 'cu15' not in result
    with pytest.raises(RuntimeError):m.allocate('cu14 3 999999 0 0 INFINITY',1)

@pytest.mark.parametrize('method',['rk4','hermite-simpson'])
def test_transcriptions_keep_a_passive_equilibrium_and_reject_unknown_method(method):
    from triple_pendulum.model import Plant,Parameters
    from triple_pendulum.optimal import optimize
    plant=Plant(Parameters(n=1));initial=np.zeros(plant.dim)
    result=optimize(plant,initial,duration=.2,nodes=11,max_iter=60,max_seconds=10,seed=42,compute_gains=False,initial_force=0.,force_rate=500.,transcription=method)
    assert result['success'] and result['defect']<1e-7
    assert np.max(np.abs(result['forces']))<1e-5
    with pytest.raises(ValueError):optimize(plant,initial,transcription='fake-animation')
