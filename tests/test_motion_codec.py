import copy,json
import numpy as np
import pytest
from triple_pendulum.motion_codec import compact_bytes
from triple_pendulum.motion_text import read_motion,loads

def document():
    rng=np.random.default_rng(12);n=3;N=40;d=n+1
    direction=dict(T=3.,h=3./39,q=rng.normal(size=(N,d)).tolist(),v=rng.normal(size=(N,d)).tolist(),a=rng.normal(size=(N,d)).tolist(),u=rng.normal(size=N).tolist(),K=rng.normal(size=(N,2*d)).tolist(),runtime_sha256='reference',proof={'final_stable':True})
    direction['u'][0]=0;direction['u'][1]=-0.;direction['K'][1][2]=1
    return dict(v=2,n=n,ends=['DDD','UUU'],model_sha256='model',basis='state-hermite-v1',ab=direction,ba=copy.deepcopy(direction))

def test_compact_storage_preserves_float_bits_integer_types_and_readable_headers():
    doc=document();raw=compact_bytes(doc);restored=read_motion(raw)
    assert json.dumps(restored,sort_keys=True)==json.dumps(doc,sort_keys=True)
    assert b'n = 3' in raw and b'coefficients = """\n' in raw
    assert all(len(line)<=120 for line in raw.decode().splitlines() if not line.startswith('#'))

def test_corrupt_or_bomb_payload_is_not_read_as_a_valid_motion():
    raw=compact_bytes(document());doc=loads(raw);doc['ab']['coefficients']='AAAA'
    from triple_pendulum.motion_codec import expand
    with pytest.raises(Exception):expand(doc)
    doc=loads(raw);doc['ab']['nodes']=20001
    with pytest.raises(ValueError):expand(doc)
