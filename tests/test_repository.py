from copy import deepcopy
from pathlib import Path
import json
import threading
import time
import uuid
import numpy as np
import pytest
from triple_pendulum.model import Plant,Parameters,wrap
from triple_pendulum.control import lqr
from triple_pendulum.validate_plan import replay
from triple_pendulum import repository

@pytest.mark.parametrize('code',repository.PATTERNS)
def test_seven_equilibria_are_passive_and_locally_stabilizable(code):
    p=Plant();goal=np.array(repository.angles(code));state=np.zeros(p.dim);state[1:p.d]=goal
    np.testing.assert_allclose(p.rhs(state),0,atol=1e-12)
    A,B=p.linearize(goal);K=lqr(p,target=goal)[0]
    assert np.linalg.eigvals(A-B@K).real.max()<-.1
    eps=1e-6;J=np.column_stack([(p.rhs(state+eps*e)-p.rhs(state-eps*e))/(2*eps) for e in np.eye(p.dim)])
    np.testing.assert_allclose(A,J,rtol=2e-8,atol=1e-7)
    rows=[r for r in repository.catalog() if r['order']==3 and r['pattern']==code]
    assert rows,f'Missing a real convergence record for {code}'
    data=repository.read(rows[0]['id']);frames=np.array(data['frames'])
    assert np.max(abs(wrap(frames[-1,2:p.d+1]-goal)))<np.deg2rad(.5)
    assert np.max(abs(frames[:,1]))<p.p.rail
    assert np.max(abs(frames[:,-1]))<=p.p.max_force

def test_winding_and_velocity_capture_without_modifying_initial_state():
    from triple_pendulum.planning_service import certified_plan
    p=Plant(Parameters(n=2));s=np.zeros(p.dim);s[1:p.d]=[-np.pi,3*np.pi];s[1]+=.008;s[-1]=.01
    saved=s.copy();result=certified_plan(p,s,4,42)
    assert result['success'];np.testing.assert_array_equal(s,saved)
    assert result['verification']['final_stable']
    np.testing.assert_array_equal(result['initial'],s)

def test_repository_deduplicates_initial_target_and_retains_angular_velocities(tmp_path,monkeypatch):
    p=Plant();source=json.loads(Path('results/verified-3.json').read_text());h=np.load('results/audit-3.npz')['history']
    monkeypatch.setattr(repository,'ROOT',tmp_path/'repository')
    a=repository.store(source,p,h);b=repository.store(source,p,h)
    assert a['id']==b['id'];assert len(repository.catalog())==1
    data=repository.read(a['id']);assert len(data['initial'])==8
    np.testing.assert_array_equal(data['initial'][5:],source['initial'][5:])
    assert len(data['frames'][0])==10
    assert data['frames'][0][0]==0
    with pytest.raises(ValueError):repository.read('../arbitrary-file')

def test_live_record_rejects_false_success_and_preserves_success(tmp_path,monkeypatch):
    row=next(r for r in repository.catalog() if r['order']==3 and r['pattern']=='UDU')
    data=repository.read(row['id']);monkeypatch.setattr(repository,'ROOT',tmp_path/'live')
    clip={k:data[k] for k in ['parameters','target_angles','frames','settled_at','sample_dt']}
    result=repository.store_live(deepcopy(clip));assert result['status']=='recorded';assert result['pattern']=='UDU'
    bad=deepcopy(clip);bad['frames'][-1][2]+=.5
    with pytest.raises(ValueError,match='未连续稳定'):repository.store_live(bad)
    bad=deepcopy(clip);bad['frames'][1][0]=bad['frames'][0][0]
    with pytest.raises(ValueError,match='时间戳'):repository.store_live(bad)

def test_new_plan_cancels_stale_job_instead_of_returning_conflict(monkeypatch):
    from triple_pendulum import server
    started=threading.Event()
    def fake(plant,initial,duration,seed,cancel,progress,target):
        started.set()
        if seed==1:
            assert cancel.wait(2),'Stale search was not cancelled'
            raise InterruptedError()
        return {'success':True}
    monkeypatch.setattr(server,'certified_plan',fake)
    common=dict(parameters=Parameters(n=1).dict(),state=[0,np.pi,0,0],client_id='cancellation-test')
    a=server.start_plan({**common,'seed':1,'request_id':str(uuid.uuid4())});assert started.wait(1)
    b=server.start_plan({**common,'seed':2,'request_id':str(uuid.uuid4())})
    server.jobs[b['id']]['future'].result(timeout=3)
    assert server.get_plan(a['id'])['status']=='cancelled'
    assert server.get_plan(b['id'])['plan']['success']

def test_replay_sampling_and_pause_controls(tmp_path):
    import subprocess
    source=next(r for r in repository.catalog() if r['order']==3 and r['pattern']=='UDU')
    path=tmp_path/'clip.json';path.write_text(json.dumps(repository.read(source['id'])),encoding='utf8')
    result=subprocess.run(['node','tests/check-replay.mjs',str(path)],text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
