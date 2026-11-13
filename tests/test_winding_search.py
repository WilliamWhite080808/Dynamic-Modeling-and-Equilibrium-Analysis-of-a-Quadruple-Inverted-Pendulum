from itertools import product
import pytest
from triple_pendulum.precompute_equilibria import winding_for,ATTEMPTS_PER_ROUND


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
