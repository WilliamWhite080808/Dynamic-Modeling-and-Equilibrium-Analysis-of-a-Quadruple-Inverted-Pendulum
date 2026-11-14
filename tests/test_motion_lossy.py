import base64,struct
import numpy as np
import pytest
from triple_pendulum.motion_lossy import GRIDS,pack_stream,unpack_stream,unshuffled_bits,shuffled_bits,acceptance_token,expand


def test_quantization_has_explicit_absolute_error_bound():
    x=np.r_[np.linspace(-30,30,1001),-0.,np.pi]
    for grid in GRIDS:
        for step in grid:
            y=np.rint(x/step)*step
            assert np.all(abs(y-x)<=step*.500001+1e-14)


def test_reversible_storage_does_not_change_quantized_integers():
    values=np.array([[0,2**63,55],[2**64-1,17,0]],dtype='<u8')
    body=pack_stream(shuffled_bits(values));raw=unpack_stream(body)
    assert np.array_equal(unshuffled_bits(raw,2,3),values)
    with pytest.raises(Exception):unpack_stream(body+'x')


def test_non_lossy_versions_or_unrecognized_codec_are_rejected():
    with pytest.raises(ValueError,match='Invalid lossy'):expand(dict(v=4,n=1))
    with pytest.raises(ValueError,match='Invalid lossy'):expand(dict(v=5,n=1,codec='unverified'))


def test_unstable_or_unaudited_candidate_cannot_get_acceptance_token():
    with pytest.raises(ValueError,match='Unaccepted'):acceptance_token({},dict(final_stable=False),{})
