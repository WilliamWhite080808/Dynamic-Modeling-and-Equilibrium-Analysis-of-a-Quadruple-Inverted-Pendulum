import numpy as np
import pytest
from triple_pendulum.model import Plant,Parameters
from triple_pendulum.direct_quality import intermediate_hold

def test_direct_motion_cannot_hide_a_stationary_third_pose():
    p=Plant(Parameters(n=4));x=np.zeros((151,p.dim));x[:,4]=np.pi
    quality=intermediate_hold(p,x,.02,'DDDD','UUUU')
    assert not quality['passed'] and quality['pose']=='UUUD' and quality['seconds']>1
    x[:,p.d+1]=.3
    assert intermediate_hold(p,x,.02,'DDDD','UUUU')['passed']

def test_departure_and_arrival_rest_are_allowed():
    p=Plant(Parameters(n=4));x=np.zeros((151,p.dim));x[:75,1:p.d]=np.pi
    assert intermediate_hold(p,x,.02,'DDDD','UUUU')['passed']

@pytest.mark.parametrize('module',['optimal','implicit_optimal'])
@pytest.mark.parametrize('fraction',[0.,-.1,1.01])
def test_search_margin_cannot_exceed_the_physical_actuator(module,fraction):
    import importlib
    p=Plant(Parameters(n=1))
    with pytest.raises(ValueError,match='physical actuator limit'):importlib.import_module('triple_pendulum.'+module).optimize(p,np.zeros(p.dim),force_fraction=fraction)
