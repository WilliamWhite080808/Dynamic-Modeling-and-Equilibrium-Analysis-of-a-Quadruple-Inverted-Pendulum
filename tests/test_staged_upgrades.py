import hashlib,json
import pytest
from triple_pendulum import transitions,repository,remote_transitions as remote

def test_only_an_audited_upgrade_replaces_the_live_index(tmp_path,monkeypatch):
    bank=tmp_path/'equilibrium_transitions';bank.mkdir();repo=tmp_path/'repository';results=tmp_path/'results'
    key='4-UUUU-UUUD';old=b'{"version":"old"}';name=key+'.json';(bank/name).write_bytes(old)
    row=dict(order=4,source='UUUU',target='UUUD',status='ready',file=name,sha256=hashlib.sha256(old).hexdigest())
    (bank/'status.json').write_text(json.dumps(dict(schema=2,entries={key:row})))
    monkeypatch.setattr(transitions,'ROOT',bank);monkeypatch.setattr(transitions,'_initialized_root',None)
    monkeypatch.setattr(repository,'ROOT',repo);monkeypatch.setattr(remote,'RESULTS',results)
    stage=__import__('pathlib').Path(remote.prepare_upgrade());candidate=b'{"version":"new"}'
    (stage/'equilibrium_transitions'/name).write_bytes(candidate);proposed=dict(row,sha256=hashlib.sha256(candidate).hexdigest())
    (stage/'equilibrium_transitions/status.json').write_text(json.dumps(dict(schema=2,entries={key:proposed})))
    def fail(*a):raise ValueError('continuous tour failed')
    monkeypatch.setattr(remote,'full_worker_audit',fail)
    with pytest.raises(ValueError,match='continuous tour failed'):remote.audit_and_promote(stage)
    assert transitions.ROOT==bank and transitions.statuses()[key]['sha256']==row['sha256']
    def audit(output):
        assert (bank/name).read_bytes()==old
        assert json.loads((bank/'status.json').read_text())['entries'][key]['sha256']==row['sha256']
        remote.atomic_json(output/'fourth-order-worker-audit.json',dict(passed=True,bank_sha256=transitions.bank_signature()))
        return True
    monkeypatch.setattr(remote,'full_worker_audit',audit)
    assert remote.audit_and_promote(stage)==1
    new=transitions.statuses()[key];assert new['sha256']==proposed['sha256'] and new['file']!=name
    assert (bank/name).read_bytes()==old and (bank/new['file']).read_bytes()==candidate
    assert (results/'fourth-order-worker-audits'/(transitions.bank_signature()+'.json')).exists()

def test_tour_certificate_registry_matches_the_exact_bank(tmp_path,monkeypatch):
    bank=tmp_path/'equilibrium_transitions';bank.mkdir();rows={}
    for source in transitions.patterns(4):
        for target in transitions.patterns(4):
            if source!=target:rows[transitions.key(4,source,target)]=dict(order=4,source=source,target=target,status='ready',sha256='immutable')
    (bank/'status.json').write_text(json.dumps(dict(schema=2,entries=rows)))
    monkeypatch.setattr(transitions,'ROOT',bank);monkeypatch.setattr(transitions,'_initialized_root',None)
    signature=transitions.bank_signature();registry=tmp_path/'results/fourth-order-worker-audits';registry.mkdir(parents=True)
    proof=registry/(signature+'.json');proof.write_text(json.dumps(dict(passed=True,bank_sha256=signature)))
    assert transitions.catalog(4)['cruise_ready'][4]
    proof.write_text(json.dumps(dict(passed=True,bank_sha256='different')))
    assert not transitions.catalog(4)['cruise_ready'][4]
