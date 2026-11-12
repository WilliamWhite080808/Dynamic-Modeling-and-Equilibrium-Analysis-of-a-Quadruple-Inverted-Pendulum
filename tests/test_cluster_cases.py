import json
from contextlib import contextmanager
from triple_pendulum import transitions,repository
from triple_pendulum.route_seeds import shortest_route,route_candidates

def test_cluster_progress_and_certificates_never_take_global_lock(tmp_path,monkeypatch):
    root=tmp_path/'bank';root.mkdir()
    k='4-UUUU-UUUD';base=dict(order=4,source='UUUU',target='UUUD',status='queued')
    (root/'status.json').write_text(json.dumps(dict(schema=2,entries={k:base})))
    monkeypatch.setattr(transitions,'ROOT',root);monkeypatch.setattr(transitions,'CLUSTER_MODE',True)
    @contextmanager
    def forbidden():raise AssertionError('Global lock in per-case cluster mode');yield
    monkeypatch.setattr(repository,'disk_lock',forbidden)
    transitions.update(4,'UUUU','UUUD',iterations=20)
    assert transitions.statuses()[k]['iterations']==20
    assert json.loads((root/'status.json').read_text())['entries'][k]['status']=='queued'
    certificate=dict(base,status='ready',sha256='abc',file='immutable.json')
    (root/'certificates'/(k+'.json')).write_text(json.dumps(certificate))
    assert transitions.statuses()[k]['status']=='ready'
    transitions.update(4,'UUUU','UUUD',status='computing')
    assert transitions.statuses()[k]['status']=='ready'
    (root/'rejections'/(k+'.json')).write_text(json.dumps(dict(sha256='abc')))
    assert transitions.statuses()[k]['status']=='retry_pending'
    certificate['sha256']='new';(root/'certificates'/(k+'.json')).write_text(json.dumps(certificate))
    assert transitions.statuses()[k]['status']=='ready'

def test_route_guess_avoids_hidden_base_detour():
    rows=[dict(source=a,target=b,duration=d,status='ready') for a,b,d in [('UU','DD',1),('DD','UD',1),('UU','DU',2),('DU','UD',2)]]
    assert shortest_route(rows,'UU','UD')==['UU','DU','UD']
    assert shortest_route(rows,'UU','DD')==['UU','DD']
    assert route_candidates(rows,'UU','UD')==[['UU','DU','UD']]

def test_direct_solution_replaces_a_certified_waypoint_path(tmp_path,monkeypatch):
    from copy import deepcopy
    from triple_pendulum.model import Plant,Parameters
    row=next(r for r in transitions.catalog(4)['entries'] if r['status']=='ready' and not r.get('route_waypoints'))
    plant=Plant(Parameters(**row['parameters']));plan=transitions.lookup(plant,row['source'],row['target']);proof=plan['verification']
    root=tmp_path/'bank';monkeypatch.setattr(transitions,'ROOT',root);monkeypatch.setattr(transitions,'_initialized_root',None)
    monkeypatch.setattr(repository,'ROOT',tmp_path/'replays');monkeypatch.setattr(repository,'store',lambda *a,**k:dict(id='test'))
    k=transitions.key(4,row['source'],row['target']);routed=deepcopy(plan);routed['route_waypoints']=[row['source'],'DDDD',row['target']]
    transitions.initialize();assert transitions.admit(plant,row['source'],row['target'],routed,proof,[])
    original=transitions.statuses()[k];assert original['route_waypoints']
    assert transitions.admit(plant,row['source'],row['target'],plan,proof,[])
    replaced=transitions.statuses()[k];assert not replaced.get('route_waypoints') and replaced['sha256']!=original['sha256']
