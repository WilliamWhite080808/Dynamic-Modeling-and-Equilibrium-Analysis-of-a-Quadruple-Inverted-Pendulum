import json
import pytest
from triple_pendulum import transitions,repository,server
from triple_pendulum.precompute_equilibria import shard_keys


def test_schema_two_upgrade_adds_992_without_changing_fourth_order_proofs(tmp_path,monkeypatch):
    bank=tmp_path/'bank';bank.mkdir()
    rows={transitions.key(4,a,b):dict(order=4,source=a,target=b,status='ready',sha256=a+b) for a in transitions.patterns(4) for b in transitions.patterns(4) if a!=b}
    original=transitions.bank_signature(list(rows.values()))
    (bank/'status.json').write_text(json.dumps(dict(schema=2,entries=rows)))
    monkeypatch.setattr(transitions,'ROOT',bank);monkeypatch.setattr(transitions,'_initialized_root',None);monkeypatch.setattr(repository,'ROOT',tmp_path/'repository')
    current=transitions.statuses()
    assert len(current)==1302 and transitions.bank_signature()==original
    assert all(current[key]==value for key,value in rows.items())
    catalog=server.transition_catalog(5)
    assert catalog['total']==992 and catalog['ready']==0 and not catalog['cruise_ready'][5]
    assert len(transitions.patterns(5))==32 and 'DDDDD' in transitions.patterns(5)
    shards=[shard_keys(catalog['entries'],8,i) for i in range(8)]
    assert all(len(shard)==124 for shard in shards)
    assert len(set.union(*shards))==992
    assert sum(map(len,shards))==len(set.union(*shards))


def test_fifth_order_sequence_requires_certificate_for_its_exact_bank(tmp_path,monkeypatch):
    bank=tmp_path/'equilibrium_transitions';bank.mkdir()
    rows={transitions.key(5,a,b):dict(order=5,source=a,target=b,status='ready',sha256=a+b) for a in transitions.patterns(5) for b in transitions.patterns(5) if a!=b}
    (bank/'status.json').write_text(json.dumps(dict(schema=2,entries=rows)))
    monkeypatch.setattr(transitions,'ROOT',bank);monkeypatch.setattr(transitions,'_initialized_root',None);monkeypatch.setattr(repository,'ROOT',tmp_path/'repository')
    assert not transitions.catalog(5)['cruise_ready'][5]
    results=tmp_path/'results';results.mkdir();proof=results/'fifth-order-worker-audit.json'
    proof.write_text(json.dumps(dict(passed=True,bank_sha256=transitions.bank_signature())))
    assert not transitions.catalog(5)['cruise_ready'][5], 'Fourth-order certificate must not authorize fifth-order sequences'
    proof.write_text(json.dumps(dict(passed=True,bank_sha256=transitions.bank_signature(order=5))))
    assert transitions.catalog(5)['cruise_ready'][5]
    current=transitions.statuses();current['5-UUUUU-UUUUD']['sha256']='updated-plan';transitions._write(current)
    assert not transitions.catalog(5)['cruise_ready'][5]
