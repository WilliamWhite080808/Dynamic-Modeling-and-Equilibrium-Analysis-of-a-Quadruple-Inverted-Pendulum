from pathlib import Path
import json
from triple_pendulum.motion_text import dumps,loads,motion_bytes,read_motion
from triple_pendulum.motion_plugins import pack,unpack,runtime,MotionStore,digest
from triple_pendulum.model import Parameters

ROOT=Path(__file__).resolve().parent.parent

def test_toml_nodes_are_multiline_and_lossless():
    a=json.loads((ROOT/'equilibrium_transitions/1-U-D.json').read_text(encoding='utf8'))
    b=json.loads((ROOT/'equilibrium_transitions/1-D-U.json').read_text(encoding='utf8'))
    model=dict(v=1,parameters={k:v for k,v in Parameters().dict().items() if k!='n'})
    doc=dict(n=1,ends=['U','D'],model_sha256=digest(model),ab=pack(a),ba=pack(b))
    raw=motion_bytes(doc);assert len(raw.splitlines())>400
    assert b'\nq = [\n  [' in raw
    parsed=read_motion(raw)
    assert runtime(unpack(parsed['ab'],1,'U','D',Parameters(n=1).dict()))==runtime(a)
    assert runtime(unpack(parsed['ba'],1,'D','U',Parameters(n=1).dict()))==runtime(b)
    # h is inferred when exactly reconstructible; default initial state omitted.
    assert b'\nh = ' not in raw and b'\ninitial = ' not in raw

def test_toml_and_legacy_json_catalogs_match(tmp_path):
    from tests.test_motion_plugins import pair
    path,source=pair(tmp_path,1,'U','D');doc=json.loads(path.read_bytes());model=json.loads((tmp_path/'models/standard.json').read_bytes())
    path.unlink();(tmp_path/'models/standard.json').unlink()
    (tmp_path/'models/standard.toml').write_text(dumps(model),encoding='utf8')
    (tmp_path/'motions/1_U_D.toml').write_bytes(motion_bytes(doc))
    store=MotionStore(tmp_path);assert store.orders()==[1] and store.catalog()['ready']==2
    assert store.refresh()['changed'] is False
