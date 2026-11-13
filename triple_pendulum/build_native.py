"""Build portable CPU kernels; recipients need NumPy/SciPy, not Numba/LLVM."""
from pathlib import Path
import argparse,os
import numpy as np
from numba import njit
from numba.pycc import CC
from . import model,recovery


@njit
def hs_predict(state,u0,u1,h,H,a,total_mass,gravity,damping,cart_damping):
    args=(H,a,total_mass,gravity,damping,cart_damping)
    first=model.dynamics(state,u0,*args)
    second=model.dynamics(state+h/2*first,(u0+u1)/2,*args)
    third=model.dynamics(state+h/2*second,(u0+u1)/2,*args)
    fourth=model.dynamics(state+h*third,u1,*args)
    rk=state+h/6*(first+2*second+2*third+fourth);guess=rk.copy()
    for _ in range(12):
        last=model.dynamics(guess,u1,*args)
        middle=(state+guess)/2+h/8*(first-last)
        fm=model.dynamics(middle,(u0+u1)/2,*args)
        guess=state+h/6*(first+4*fm+last)
    if not np.isfinite(guess).all() or np.max(np.abs(guess-rk))>10:return rk
    return guess


@njit
def state_corrections(states,forces,h,H,a,total_mass,gravity,damping,cart_damping):
    bits=states.view(np.uint64).copy()
    for k in range(1,len(states)):
        predicted=hs_predict(states[k-1],forces[k-1],forces[k],h,H,a,total_mass,gravity,damping,cart_damping)
        bits[k]^=predicted.view(np.uint64)
    return bits


@njit
def restore_states(corrections,forces,h,H,a,total_mass,gravity,damping,cart_damping):
    bits=corrections.copy();states=bits.view(np.float64)
    for k in range(1,len(states)):
        predicted=hs_predict(states[k-1],forces[k-1],forces[k],h,H,a,total_mass,gravity,damping,cart_damping)
        bits[k]^=predicted.view(np.uint64)
    return states


def build(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    class FixedMathCC(CC):
        def _compile_mixins(self,build_dir):
            objects=super()._compile_mixins(build_dir)
            fdlibm=Path(__file__).resolve().parent.parent/'native/fdlibm'
            flags=['/fp:strict','/Oi-'] if os.name=='nt' else ['-ffp-contract=off','-fno-fast-math']
            objects+=self._toolchain.compile_objects([str(p) for p in sorted(fdlibm.glob('*.c'))],build_dir,include_dirs=[str(fdlibm)],macros=[('__STDC__','1'),('__LITTLE_ENDIAN','1')],extra_cflags=flags)
            return objects
    cc=FixedMathCC('_native');cc.output_dir=str(destination.resolve());cc.target_cpu='generic'
    args='f8[:,:],f8[:],f8,f8,f8,f8'
    cc.export('acceleration','f8[:](f8[:],f8[:],f8,'+args+')')(model.acceleration.py_func)
    cc.export('dynamics','f8[:](f8[:],f8,'+args+')')(model.dynamics.py_func)
    cc.export('batch_dynamics','f8[:,:](f8[:,:],f8[:],'+args+')')(model.batch_dynamics.py_func)
    cc.export('dissipative_force','f8(f8[:],f8,f8,f8,f8,f8,f8)')(recovery.dissipative_force.py_func)
    cc.export('dissipative_rollout','Tuple((f8[:,:],f8[:]))(f8[:],f8,f8,f8,f8,f8,f8,'+args+')')(recovery.dissipative_rollout.py_func)
    cc.export('state_corrections','u8[:,:](f8[:,:],f8[:],f8,'+args+')')(state_corrections.py_func)
    cc.export('restore_states','f8[:,:](u8[:,:],f8[:],f8,'+args+')')(restore_states.py_func)
    cc.compile()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination');build(parser.parse_args().destination)
