"""Encode with the pinned recipient interpreter and AOT math, including workers."""
import argparse,importlib.util,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
os.environ['OPENBLAS_CORETYPE']='NEHALEM'
os.environ['NPY_DISABLE_CPU_FEATURES']='SSSE3,SSE41,POPCNT,SSE42,AVX,F16C,FMA3,AVX2,AVX512F,AVX512CD,AVX512_SKX,AVX512_CLX,AVX512_CNL,AVX512_ICL'
kernel=os.environ.get('PENDULUM_NATIVE_KERNEL')
if kernel is None:
    kernel=str(Path(sys.argv[sys.argv.index('--kernel')+1]).resolve());os.environ['PENDULUM_NATIVE_KERNEL']=kernel
spec=importlib.util.spec_from_file_location('triple_pendulum._native',kernel)
native=importlib.util.module_from_spec(spec);sys.modules[spec.name]=native;spec.loader.exec_module(native)
from triple_pendulum.build_compact import encode

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kernel',required=True);p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    report=encode(a.source,a.output,a.workers)
    print({k:v for k,v in report.items() if k!='files'},flush=True)
