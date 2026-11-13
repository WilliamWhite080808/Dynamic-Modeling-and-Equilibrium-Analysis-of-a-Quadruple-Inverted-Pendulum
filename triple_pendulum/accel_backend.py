"""Optional ahead-of-time kernels; source computations retain the Numba path."""
try:
    from . import _native as native
except ImportError as native_error:
    native=None
    try:
        from numba import njit
    except ImportError:
        raise ImportError('计算内核载入失败，请完整解压应用；无需另行安装Numba。') from native_error
else:
    def njit(*args,**kwargs):
        return lambda function:function
