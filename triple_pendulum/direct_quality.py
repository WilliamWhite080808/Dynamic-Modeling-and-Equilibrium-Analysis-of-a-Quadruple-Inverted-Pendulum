"""Detect an unintended stop at a third equilibrium in a direct trajectory."""
import numpy as np
from .model import wrap
from . import repository,transitions

def intermediate_hold(plant,states,dt,source,target,edge_seconds=.6):
    x=np.asarray(states);times=np.arange(len(x))*dt;interior=(times>edge_seconds)&(times<times[-1]-edge_seconds)
    longest=0.;pose=None
    for code in transitions.patterns(plant.n):
        if code in (source,target):continue
        near=interior & (np.max(abs(wrap(x[:,1:plant.d]-repository.angles(code))),axis=1)<np.deg2rad(3)) & (np.max(abs(x[:,plant.d+1:]),axis=1)<.15) & (abs(x[:,plant.d])<.08)
        run=0
        for value in near:
            run=run+1 if value else 0
            if run*dt>longest:longest=run*dt;pose=code
    return dict(seconds=longest,pose=pose,passed=longest<=.25)
