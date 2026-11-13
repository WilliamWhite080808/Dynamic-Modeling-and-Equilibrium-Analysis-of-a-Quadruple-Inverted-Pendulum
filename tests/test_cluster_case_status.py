import json
from triple_pendulum import transitions

def test_direct_case_status_matches_full_scan_and_rejection(tmp_path,monkeypatch):
    root=tmp_path/'bank';root.mkdir();key='5-UUUUU-DDDDD'
    seed=dict(order=5,source='UUUUU',target='DDDDD',status='queued')
    (root/'status.json').write_text(json.dumps(dict(entries={key:seed})))
    monkeypatch.setattr(transitions,'ROOT',root);monkeypatch.setattr(transitions,'CLUSTER_MODE',True)
    assert transitions.case_status(5,'UUUUU','DDDDD')==seed
    progress=root/'progress'/(key+'.json');progress.write_text(json.dumps(dict(seed,status='computing',iterations=12)))
    assert transitions.case_status(5,'UUUUU','DDDDD')==transitions.statuses()[key]
    certificate=root/'certificates'/(key+'.json');certificate.write_text(json.dumps(dict(seed,status='ready',sha256='old')))
    assert transitions.case_status(5,'UUUUU','DDDDD')==transitions.statuses()[key]
    (root/'rejections'/(key+'.json')).write_text(json.dumps(dict(sha256='old')))
    assert transitions.case_status(5,'UUUUU','DDDDD')==transitions.statuses()[key]
    assert transitions.case_status(5,'UUUUU','DDDDD')['status']=='retry_pending'
    certificate.write_text(json.dumps(dict(seed,status='ready',sha256='new')))
    assert transitions.case_status(5,'UUUUU','DDDDD')==transitions.statuses()[key]
    assert transitions.case_status(5,'UUUUU','DDDDD')['sha256']=='new'

def test_per_case_read_never_scans_unrelated_progress(tmp_path,monkeypatch):
    root=tmp_path/'bank';root.mkdir();key='5-UUUUU-DDDDD';seed=dict(order=5,source='UUUUU',target='DDDDD',status='queued')
    (root/'status.json').write_text(json.dumps(dict(entries={key:seed})))
    monkeypatch.setattr(transitions,'ROOT',root);monkeypatch.setattr(transitions,'CLUSTER_MODE',True)
    transitions.search_manifest()
    def forbidden():raise AssertionError('Per-case search must not enumerate the global bank')
    monkeypatch.setattr(transitions,'statuses',forbidden)
    assert transitions.case_status(5,'UUUUU','DDDDD')==seed
