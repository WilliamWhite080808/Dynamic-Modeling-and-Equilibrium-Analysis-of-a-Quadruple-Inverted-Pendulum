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
