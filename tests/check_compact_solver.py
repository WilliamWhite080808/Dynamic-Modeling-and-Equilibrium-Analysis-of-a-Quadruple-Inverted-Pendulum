"""Run with the recipient's unpacked interpreter, never developer dependencies."""
import json,sys,time,shutil
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import numpy as np
from triple_pendulum.model import Plant,Parameters
from triple_pendulum.control import analyze
from triple_pendulum.optimal import optimize
from triple_pendulum.validate_plan import replay

def main():
    output=Path(sys.argv[2]);reference=json.loads(Path(sys.argv[3]).read_bytes());errors=[]
    for row in reference:
        p=Plant(Parameters(**row['parameters']));actual=p.batch(np.array(row['states']),np.array(row['forces']))
        error=float(np.max(abs(actual-np.array(row['derivatives']))));errors.append(error)
        assert np.allclose(actual,row['derivatives'],rtol=5e-13,atol=1e-11),(p.n,error)
    for n in range(1,6):analyze(Plant(Parameters(n=n)))
    p=Plant(Parameters(n=1));initial=np.zeros(p.dim);initial[1]=np.pi;started=time.monotonic()
    solved=optimize(p,initial,5,201,max_seconds=50,max_iter=600,initial_force=0.,force_rate=500.)
    assert solved['success'];solved.update(force_rate=500.,strict_rest=True)
    report=replay(p,solved,total=15);report.pop('history')
    assert report['final_stable'] and report['max_force']<=120.000001 and report['max_force_rate']<=500.000001 and report['max_cart']<2.304
    result=dict(passed=True,interpreter=sys.executable,numba_imported='numba' in sys.modules,
        rhs_random_cases=len(reference),max_absolute_rhs_difference=max(errors),orders_analyzed=[1,2,3,4,5],
        fresh_ipopt_hanging_swingup=True,solver_seconds=time.monotonic()-started,verification=report)
    from triple_pendulum.motion_plugins import MotionStore,atomic
    test=output.parent/'v4-cache-semantics';test.mkdir(exist_ok=False);(test/'motions').mkdir()
    app=Path(sys.argv[1]);shutil.copytree(app/'models',test/'models')
    shutil.copy2(app/'motions/1_D_U.toml',test/'motions/1_D_U.toml')
    store=MotionStore(test);assert store.orders()==[1]
    store.value['source_preload']=True;atomic(store.index,store.value)
    shutil.copy2(app/'motions/2_DD_UU.toml',test/'motions/2_DD_UU.toml')
    assert MotionStore(test).orders()==[1]
    assert store.refresh()['orders']==[1,2]
    store.index.write_text('{broken');rebuilt=MotionStore(test);assert rebuilt.orders()==[1,2]
    assert list((test/'.cache').glob('trajectory-index.bad-*.json'))
    result.update(v4_first_index_rebuilt=True,v4_manual_activation=True,v4_broken_index_rebuilt=True)
    assert not result['numba_imported'];output.write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
