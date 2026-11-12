import numpy as np
import pytest
from triple_pendulum import transitions
from triple_pendulum.model import Plant,Parameters
from triple_pendulum.validate_plan import replay
from triple_pendulum.audit_fifth import independent_balance


def test_com_balance_detects_an_extra_joint_drive(monkeypatch):
    plant=Plant(Parameters(n=5));state=np.array([.2,.3,-.7,1.2,2.5,-2.,.4,1.,-2.,.7,1.8,-.5])
    original=plant.rhs
    proof=independent_balance(plant,state,17.)
    assert max(proof.values())<1e-10
    def driven(state,force):
        result=original(state,force).copy();result[plant.d+3]+=.4;return result
    monkeypatch.setattr(plant,'rhs',driven)
    assert independent_balance(plant,state,17.)['joint_torque_residual']>1e-3


def test_step_refinement_preserves_control_hold_and_default_behavior(monkeypatch):
    plant=Plant(Parameters(n=1));plan=transitions.lookup(plant,'D','U')
    original=plant.rk4;forces=[]
    def recorded(state,force,step):forces.append(force);return original(state,force,step)
    monkeypatch.setattr(plant,'rk4',recorded)
    default=replay(plant,plan,total=.08)
    explicit=replay(plant,plan,total=.08,control_period=.004)
    np.testing.assert_array_equal(default['history'],explicit['history'])
    forces.clear();fine=replay(plant,plan,dt=.0005,total=.08,control_period=.004)
    assert len(forces)==160
    assert any(abs(value)>1e-8 for value in forces)
    for start in range(0,len(forces),8):assert len(set(forces[start:start+8]))==1
    assert fine['max_force_rate']<=500.000001


@pytest.mark.parametrize('period',[0.,-.004,.00075])
def test_nonintegral_or_nonpositive_control_period_is_rejected(period):
    with pytest.raises(ValueError,match='Control period'):
        replay(None,{},dt=.0005,control_period=period)
