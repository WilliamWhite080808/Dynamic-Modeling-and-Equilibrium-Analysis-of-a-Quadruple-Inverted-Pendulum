from pathlib import Path
import json
import numpy as np
from triple_pendulum.motion_plugins import MotionStore,pack,unpack,encoded,digest,runtime
from triple_pendulum.model import Plant,Parameters

ROOT=Path(__file__).resolve().parent.parent

def pair(tmp,n,a,b):
    model=dict(v=1,parameters={k:v for k,v in Parameters().dict().items() if k!='n'},sequence_signatures={})
    (tmp/'models').mkdir(exist_ok=True);(tmp/'models/standard.json').write_bytes(encoded(model));(tmp/'motions').mkdir(exist_ok=True)
    source=json.loads((ROOT/f'equilibrium_transitions/{n}-{a}-{b}.json').read_text(encoding='utf8'))
    reverse=json.loads((ROOT/f'equilibrium_transitions/{n}-{b}-{a}.json').read_text(encoding='utf8'))
    doc=dict(v=1,n=n,ends=[a,b],basis='state-hermite-v1',model_sha256=digest(model),ab=pack(source),ba=pack(reverse))
    path=tmp/f'motions/n{n}_{a}_{b}.motion.json';path.write_bytes(encoded(doc));return path,source

def test_parameterization_preserves_every_controller_number(tmp_path):
    path,source=pair(tmp_path,1,'U','D');doc=json.loads(path.read_bytes())
    restored=unpack(doc['ab'],1,'U','D',Parameters(n=1).dict())
    assert runtime(restored)==runtime(source)
    assert digest(runtime(restored))==digest(runtime(source))

def test_source_changes_are_inactive_until_explicit_scan(tmp_path):
    path,source=pair(tmp_path,1,'U','D');store=MotionStore(tmp_path)
    pair(tmp_path,2,'UU','DD')
    assert store.orders()==[1]
    assert MotionStore(tmp_path).orders()==[1]
    assert store.refresh()['orders']==[1,2]
    saved=store.lookup(Plant(Parameters(n=1)),'U','D')
    path.write_text('{invalid',encoding='utf8')
    assert store.lookup(Plant(Parameters(n=1)),'U','D')==saved
    result=store.refresh();assert len(result['errors'])==1
    assert MotionStore(tmp_path).lookup(Plant(Parameters(n=1)),'U','D')==saved
    path.unlink();store.refresh();assert store.orders()==[2]

def test_bad_reverse_cannot_publish_a_pair(tmp_path):
    path,_=pair(tmp_path,1,'U','D');doc=json.loads(path.read_bytes());doc['ba']['u'][3]+=1;path.write_bytes(encoded(doc))
    store=MotionStore(tmp_path);assert store.orders()==[];assert store.catalog()['ready']==0

def test_fast_cache_loads_without_reparsing_source_and_checks_its_hash(tmp_path,monkeypatch):
    import pytest
    import triple_pendulum.motion_plugins as module
    pair(tmp_path,1,'U','D');store=MotionStore(tmp_path)
    meta=next(iter(store.value['files'].values()));assert meta['ext']=='.json.gz'
    expected=store.lookup(Plant(Parameters(n=1)),'U','D')
    monkeypatch.setattr(module,'read_motion',lambda *args:(_ for _ in ()).throw(AssertionError('reparsed source')))
    assert MotionStore(tmp_path).lookup(Plant(Parameters(n=1)),'U','D')==expected
    cached=store.cache/(meta['cache_sha256']+meta['ext']);cached.write_bytes(b'broken')
    with pytest.raises(ValueError,match='缓存损坏'):MotionStore(tmp_path).lookup(Plant(Parameters(n=1)),'U','D')

def test_build_preload_refreshes_new_build_but_refuses_started_instance(tmp_path):
    import pytest
    from triple_pendulum.build_editions import prepare_cache
    pair(tmp_path,1,'U','D');assert prepare_cache(tmp_path)['pairs']==1
    pair(tmp_path,2,'UU','DD');assert prepare_cache(tmp_path)['pairs']==2
    (tmp_path/'.cache/instance.json').write_text('{}')
    with pytest.raises(ValueError,match='已运行应用'):prepare_cache(tmp_path)

def compact_pair(tmp,n,a,b):
    from triple_pendulum.motion_codec import compact_bytes
    old,source=pair(tmp,n,a,b);doc=json.loads(old.read_bytes());path=old.with_name(f'{n}_{a}_{b}.toml')
    path.write_bytes(compact_bytes(doc));old.unlink();return path,source

def test_compact_prebuilt_index_restores_missing_snapshots_without_parsing(tmp_path,monkeypatch):
    import triple_pendulum.motion_plugins as module
    path,_=compact_pair(tmp_path,1,'U','D');store=MotionStore(tmp_path);meta=next(iter(store.value['files'].values()))
    assert meta['seed_source']==path.name and meta['ext']=='.toml'
    cached=store.cache/(meta['cache_sha256']+meta['ext']);cached.unlink()
    with monkeypatch.context() as patch:
        patch.setattr(module,'read_motion',lambda *args:(_ for _ in ()).throw(AssertionError('startup parsed coefficients')))
        rebuilt=MotionStore(tmp_path);assert rebuilt.orders()==[1] and rebuilt.catalog()['ready']==2
    assert cached.read_bytes()==path.read_bytes()
    before=rebuilt.lookup(Plant(Parameters(n=1)),'U','D')
    compact_pair(tmp_path,2,'UU','DD');path.write_text('broken')
    assert MotionStore(tmp_path).orders()==[1]
    assert MotionStore(tmp_path).lookup(Plant(Parameters(n=1)),'U','D')==before

def test_missing_or_broken_index_is_rebuilt_and_changed_missing_seed_requires_manual_update(tmp_path):
    path,_=compact_pair(tmp_path,1,'U','D');store=MotionStore(tmp_path)
    store.index.unlink();assert MotionStore(tmp_path).catalog()['ready']==2
    store.index.write_text('{broken');assert MotionStore(tmp_path).catalog()['ready']==2
    assert list((tmp_path/'.cache').glob('trajectory-index.bad-*.json'))
    meta=next(iter(store.value['files'].values()));(store.cache/(meta['cache_sha256']+meta['ext'])).unlink();path.write_text('broken')
    invalid=MotionStore(tmp_path);assert invalid.orders()==[] and invalid.seed_errors
