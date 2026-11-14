"""Same deterministic numerical probes under original and modified libraries."""
import argparse,atexit,collections,ctypes,hashlib,json,os,sys,time
from pathlib import Path

def loaded_dlls(root):
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32');psapi=ctypes.WinDLL('psapi')
    kernel.GetCurrentProcess.restype=wintypes.HANDLE;handle=kernel.GetCurrentProcess()
    modules=(ctypes.c_void_p*2048)();size=wintypes.DWORD()
    psapi.EnumProcessModulesEx.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.DWORD]
    psapi.GetModuleFileNameExW.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.LPWSTR,wintypes.DWORD]
    assert psapi.EnumProcessModulesEx(handle,modules,ctypes.sizeof(modules),ctypes.byref(size),3)
    rows=[]
    for module in modules[:size.value//ctypes.sizeof(ctypes.c_void_p)]:
        buffer=ctypes.create_unicode_buffer(32768)
        if psapi.GetModuleFileNameExW(handle,module,buffer,len(buffer)):
            p=Path(buffer.value)
            if p.is_relative_to(root):rows.append(p.relative_to(root).as_posix())
    return sorted(rows)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('app');parser.add_argument('output');parser.add_argument('--profile',action='store_true');a=parser.parse_args()
    app=Path(a.app).resolve();output=Path(a.output).resolve();output.mkdir(parents=True,exist_ok=False)
    runtime=Path(sys.executable).resolve().parent;prefix=str(runtime).lower()+'\\';sys.path.insert(0,str(app))
    os.environ['PENDULUM_CACHE_HOME']=str(output/'cache')
    functions=collections.Counter();codes={}
    def profile(frame,event,arg):
        if event!='call':return
        code=frame.f_code
        key=codes.get(code,False)
        if key is False:
            name=code.co_filename
            key=(name[len(prefix):].replace('\\','/')+':'+code.co_qualname) if name.lower().startswith(prefix) else None
            codes[code]=key
        if key:functions[key]+=1
    def flush():
        sys.setprofile(None)
        modules={name:Path(m.__file__).relative_to(runtime).as_posix() for name,m in tuple(sys.modules.items()) if getattr(m,'__file__',None) and Path(m.__file__).is_relative_to(runtime)}
        (output/'coverage.json').write_text(json.dumps(dict(modules=modules,functions=dict(sorted(functions.items())),dlls=loaded_dlls(runtime)),indent=2),encoding='utf8')
    atexit.register(flush)
    if a.profile:sys.setprofile(profile)
    import itertools,numpy as np
    from triple_pendulum.model import Plant,Parameters
    from triple_pendulum.control import analyze,Observer,measurement
    from triple_pendulum.planner import plan
    from triple_pendulum.optimal import optimize
    from triple_pendulum.validate_plan import replay
    designs=[];observer_rows=[];started=time.monotonic()
    for point_mass in (False,True):
        for n in range(1,6):
            plant=Plant(Parameters(n=n,point_mass=point_mass))
            for code in itertools.product((0.,float(np.pi)),repeat=n):
                designs.append(analyze(plant,'cart_and_tip',1.,np.array(code)))
        print('PASS all equilibrium designs, point_mass',point_mass,flush=True)
    for n in (1,3,5):
        plant=Plant(Parameters(n=n,length=.55,mass=.24,cart_mass=1.8,damping=.009))
        for sensor in ('full_state','angles_only','cart_only','cart_and_tip'):
            for kind in ('kalman','ekf','luenberger'):
                observer=Observer(plant,sensor,kind);state=np.zeros(plant.dim);state[1:plant.d]=.01
                for _ in range(4):
                    state=plant.rk4(state,1.5,.004);value=observer.update(measurement(plant,state,sensor),1.5,.004)
                assert np.isfinite(value).all();observer_rows.append(value.tolist())
    print('PASS observer branches',len(observer_rows),flush=True)
    plant=Plant(Parameters(n=1));initial=np.zeros(plant.dim);initial[1]=.03
    guess=dict(duration=2.,states=np.linspace(initial,np.zeros(plant.dim),31).tolist(),forces=[0.]*31)
    legacy=plan(plant,initial,2.,31,max_nfev=100,seed=19,guess=guess)
    assert legacy['success'],{k:v for k,v in legacy.items() if k not in ('states','forces','gains','derivatives')}
    print('PASS actual sparse least-squares planner',flush=True)
    hanging=np.zeros(plant.dim);hanging[1]=np.pi
    fresh=optimize(plant,hanging,5.,201,max_seconds=50,max_iter=600,initial_force=0.,force_rate=500.)
    assert fresh['success'];fresh.update(force_rate=500.,strict_rest=True)
    verification=replay(plant,fresh,total=15.);verification.pop('history')
    assert verification['final_stable'] and verification['max_cart']<2.304 and verification['max_force']<=120.000001 and verification['max_force_rate']<=500.000001
    from triple_pendulum import server
    assert server.available_orders()==[1,2,3,4,5]
    from triple_pendulum.motion_plugins import active
    store=active();sample=[]
    for n in range(1,6):
        p=Plant(Parameters(n=n));data=store.lookup(p,'D'*n,'U'*n)
        assert data is not None;sample.append({k:data[k] for k in ('duration','dt','states','derivatives','forces','gains')})
    selected=lambda p:{k:p[k] for k in ('duration','dt','initial','target_angles','states','derivatives','forces','gains','success') if k in p}
    values=dict(designs=designs,observers=observer_rows,legacy=selected(legacy),ipopt=selected(fresh),samples=sample)
    raw=json.dumps(values,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    (output/'values.json').write_bytes(raw)
    report=dict(passed=True,designs=len(designs),observer_cases=len(observer_rows),actual_sparse_planner=True,
        fresh_ipopt_hanging_swingup=True,verification=verification,numeric_sha256=hashlib.sha256(raw).hexdigest(),seconds=time.monotonic()-started,interpreter=sys.executable)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8');flush();print(json.dumps(report),flush=True)

if __name__=='__main__':main()
