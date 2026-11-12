import json,subprocess
import numpy as np
import pytest
from fastapi import HTTPException
from triple_pendulum import transitions,repository,server
from triple_pendulum.model import Plant,Parameters
from triple_pendulum.control import analyze


def test_all_70_directed_transitions_are_certified():
    entries=[r for r in transitions.catalog()['entries'] if r['order']<=3]
    assert len(entries)==70 and all(r['status']=='ready' for r in entries)
    expected={(n,a,b) for n in (1,2,3) for a in transitions.patterns(n) for b in transitions.patterns(n) if a!=b}
    assert {(r['order'],r['source'],r['target']) for r in entries}==expected
    for row in entries:
        p=Plant(Parameters(**row['parameters']));plan=transitions.lookup(p,row['source'],row['target'])
        assert plan and not plan.get('segments'),'Each edge has a direct trajectory, never a hidden route via base'
        assert plan['pattern']==row['target']
        np.testing.assert_allclose(plan['initial'],transitions.equilibrium(p,row['source']),atol=1e-8)
        assert repository.pattern(plan['target_angles'])==row['target']
        v=plan['verification'];assert v['final_stable'] and v['max_cart']<p.p.rail*.96
        assert v['max_force']<=p.p.max_force and v['max_force_rate']<=500+1e-6


def test_runtime_transfer_is_parameter_and_source_checked():
    p=Plant(Parameters(n=2));state=transitions.equilibrium(p,'UD').tolist()
    result=server.transition_plan(dict(parameters=p.p.dict(),source='UD',target='DD',state=state))
    assert result['plan']['transition']==dict(order=2,source='UD',target='DD')
    jumped=server.transition_plan(dict(parameters=p.p.dict(),source='UD',target='DD',jump_to_start=True,state=[99]*p.dim))
    np.testing.assert_allclose(jumped['plan']['initial'],transitions.equilibrium(p,'UD'))
    for changes in (dict(source='UU'),dict(target='UD'),dict(parameters=Parameters(n=2,mass=.7).dict()),dict(state=[float('nan')]*p.dim)):
        with pytest.raises(HTTPException):server.transition_plan(dict(parameters=p.p.dict(),source='UD',target='DD',state=state)|changes)
    with pytest.raises(ValueError):transitions.patterns(6)

def test_fourth_order_covers_all_240_directed_pairs():
    catalog=transitions.catalog(4);assert catalog['total']==240
    assert len(transitions.patterns(4))==16 and 'DDDD' in transitions.patterns(4)
    assert {(r['source'],r['target']) for r in catalog['entries']}=={(a,b) for a in transitions.patterns(4) for b in transitions.patterns(4) if a!=b}
    for row in catalog['entries']:
        if row['status']=='ready':
            plan=transitions.lookup(Plant(Parameters(**row['parameters'])),row['source'],row['target'])
            assert plan['verification']['final_stable'] and plan['force_rate']==500

def test_parallel_shards_cover_240_once_without_reassigning_finished_tasks():
    from triple_pendulum.precompute_equilibria import shard_keys
    rows=transitions.catalog(4)['entries'];shards=[shard_keys(rows,3,i) for i in range(3)]
    assert [len(s) for s in shards]==[80,80,80]
    assert len(set.union(*shards))==240 and not(shards[0]&shards[1] or shards[0]&shards[2] or shards[1]&shards[2])
    changed=[dict(r,status='ready') for r in rows]
    assert [shard_keys(changed,3,i) for i in range(3)]==shards

def test_old_manifest_migration_preserves_certificates(tmp_path,monkeypatch):
    root=tmp_path/'bank';root.mkdir();entry=dict(order=1,source='U',target='D',status='ready',sha256='existing-proof')
    (root/'status.json').write_text(json.dumps(dict(schema=1,entries={'1-U-D':entry})),encoding='utf8')
    monkeypatch.setattr(transitions,'ROOT',root);monkeypatch.setattr(transitions,'_initialized_root',None);monkeypatch.setattr(repository,'ROOT',tmp_path/'repo')
    transitions.initialize();migrated=json.loads((root/'status.json').read_text())
    assert migrated['schema']==2 and len(migrated['entries'])==1302 and migrated['entries']['1-U-D']==entry

def test_ready_fourth_order_transition_is_available_to_point_play():
    rows=[r for r in transitions.catalog(4)['entries'] if r['status']=='ready']
    if not rows:pytest.skip('Fourth-order jobs have not published a certified result yet')
    row=rows[0];p=Plant(Parameters(**row['parameters']))
    result=server.transition_plan(dict(parameters=p.p.dict(),source=row['source'],target=row['target'],jump_to_start=True))
    assert len(result['design']['target_angles'])==4 and result['plan']['transition']['order']==4


def test_worker_all_hot_transfers_and_continuous_tours(tmp_path):
    designs={};fixtures=[]
    for row in transitions.catalog()['entries']:
        if row['status']!='ready':continue
        p=Plant(Parameters(**row['parameters']));k=(p.n,row['target'])
        if k not in designs:designs[k]=analyze(p,target=repository.angles(row['target']))
        source_key=(p.n,row['source'])
        if source_key not in designs:designs[source_key]=analyze(p,target=repository.angles(row['source']))
        fixtures.append(dict(design=designs[k],source_design=designs[source_key],plan=transitions.lookup(p,row['source'],row['target'])))
    path=tmp_path/'transfers.json';path.write_text(json.dumps(fixtures),encoding='utf8')
    result=subprocess.run(['node','tests/check-transfers.mjs',str(path),'results/equilibrium-worker-audit.json'],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
