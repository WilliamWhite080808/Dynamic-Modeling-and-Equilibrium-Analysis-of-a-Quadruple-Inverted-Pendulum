from itertools import product
import pytest
from triple_pendulum.precompute_equilibria import winding_for,ATTEMPTS_PER_ROUND

def test_tail_search_varies_reference_margin_inside_the_same_actuator_limit():
    from triple_pendulum.precompute_equilibria import force_fraction_for,search_duration
    fractions={force_fraction_for(a,r) for r in range(4) for a in range(8)}
    assert fractions=={.66,.8,.9} and max(fractions)<1
    assert search_duration(5,0,32,0)==7
    assert search_duration(5,7,32,0)<=11
    assert search_duration(5,7,32,17)==13


@pytest.mark.parametrize('changed',range(1,7))
def test_search_rounds_cover_all_rotation_directions(changed):
    windings=list(product((1,-1),repeat=changed))
    rounds=max(1,(len(windings)+ATTEMPTS_PER_ROUND-1)//ATTEMPTS_PER_ROUND)
    found={winding_for(windings,attempt,round_index) for round_index in range(rounds) for attempt in range(ATTEMPTS_PER_ROUND)}
    assert found==set(windings)
    assert [winding_for(windings,attempt,0) for attempt in range(ATTEMPTS_PER_ROUND)]==[windings[attempt%len(windings)] for attempt in range(ATTEMPTS_PER_ROUND)]


def test_fifth_order_continuation_explores_previously_unused_directions():
    windings=list(product((1,-1),repeat=5))
    original={windings[attempt] for attempt in range(8)}
    resumed={winding_for(windings,attempt,5) for attempt in range(8)}
    assert resumed.isdisjoint(original)
    assert len(resumed)==8
