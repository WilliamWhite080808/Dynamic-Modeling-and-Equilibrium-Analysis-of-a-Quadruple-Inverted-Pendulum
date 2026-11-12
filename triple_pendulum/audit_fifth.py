"""Audit immutable ready plans, then refine integration with fixed 250 Hz control."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
from pathlib import Path
import hashlib,json,subprocess,time
import numpy as np
from . import transitions,repository
from .model import Plant,Parameters,wrap
from .validate_plan import replay
from .control import analyze

PROJECT=Path(__file__).resolve().parent.parent

def independent_balance(plant,state,force):
    """Rebuild COM Jacobians and Newton balances without H/a/mass_matrix."""
    n,d=plant.n,plant.d;p=plant.p
    theta=state[1:d];velocity=state[d:];omega=velocity[1:]
    acceleration=plant.rhs(state,force)[d:];alpha=acceleration[1:]
    required=np.zeros(d);required[0]=p.cart_mass*acceleration[0]+p.cart_damping*velocity[0]
    energy=.5*p.cart_mass*velocity[0]**2;power=p.cart_mass*velocity[0]*acceleration[0]
    for i in range(n):
        lever=np.r_[plant.lengths[:i],plant.centers[i],np.zeros(n-i-1)]
        jx=np.r_[1.,lever*np.cos(theta)];jy=np.r_[0.,-lever*np.sin(theta)]
        vx=jx@velocity;vy=jy@velocity
        ax=jx@acceleration-np.sum(lever*np.sin(theta)*omega**2)
        ay=jy@acceleration-np.sum(lever*np.cos(theta)*omega**2)
        mass=plant.masses[i];inertia=plant.inertia[i]
        required+=mass*(jx*ax+jy*(ay+p.gravity));required[i+1]+=inertia*alpha[i]
        energy+=.5*mass*(vx*vx+vy*vy)+.5*inertia*omega[i]**2+mass*p.gravity*np.sum(lever*np.cos(theta))
        power+=mass*(vx*ax+vy*(ay+p.gravity))+inertia*omega[i]*alpha[i]
    relative=omega-np.r_[0.,omega[:-1]]
    torque=p.damping*relative
    required[1:]+=torque
    required[1:-1]-=torque[1:]
    required[0]-=force
    external_power=force*velocity[0]-p.cart_damping*velocity[0]**2-p.damping*np.sum(relative**2)
    return dict(joint_torque_residual=float(np.max(abs(required[1:]))),cart_force_residual=float(abs(required[0])),power_residual=float(abs(power-external_power)),energy_difference=float(abs(energy-plant.energy(state))))

def main():
    output=PROJECT/'results/fifth-order-correctness';output.mkdir(parents=True,exist_ok=True)
    rows=[r for r in transitions.catalog(5)['entries'] if r['status']=='ready'];assert rows
    plans={};aggregate=dict(max_cart=0.,max_force=0.,max_force_rate=0.,final_angle_deg=0.)
    for row in rows:
        data=(transitions.ROOT/row['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==row['sha256']
        plan=json.loads(data);plant=Plant(Parameters(**plan['parameters']));identity={k:row[k] for k in ('order','source','target')}
        assert plant.n==5 and plan['transition']==identity and plan['parameters']==row['parameters']
        assert not plan.get('segments') and not plan.get('route_waypoints') and plan['force_rate']==500. and plan['strict_rest']
        np.testing.assert_allclose(plan['initial'],transitions.equilibrium(plant,row['source']),atol=1e-8)
        assert repository.pattern(plan['target_angles'])==row['target']
        assert np.asarray(plan['forces']).ndim==1 and np.isfinite(np.asarray(plan['states'])).all()
        proof=plan['verification'];assert proof['final_stable'] and proof['max_cart']<.96*plant.p.rail and proof['max_force']<=plant.p.max_force and proof['max_force_rate']<=500.000001 and proof['max_tracking_error']<3
        worker=plan['worker_verification'];assert worker['rail_contacts']==0 and worker['live_planner_requests']==0 and len(worker['individual'])==1
        record=worker['individual'][0];assert all(record[k]==v for k,v in identity.items())
        assert record['angle_deg']<.5 and record['max_cart']<.96*plant.p.rail and record['max_force']<=plant.p.max_force+1e-8 and record['max_force_rate']<=500.000001
        assert plan['direct_quality']['passed'] and plan['direct_quality']['seconds']<=.25
        for key in aggregate:aggregate[key]=max(aggregate[key],proof[key])
        plans[transitions.key(5,row['source'],row['target'])]=plan
    selected=[]
    hanging=[r for r in rows if r['source']=='DDDDD']
    for row in ([hanging[0]] if hanging else [])+[rows[0]]+[max(rows,key=lambda r:r['verification'][field]) for field in ('max_force','max_cart','final_angle_deg')]+[max(rows,key=lambda r:r['duration'])]:
        if row['file'] not in {r['file'] for r in selected}:selected.append(row)
    cases=[];fixtures=[]
    for row in selected:
        key=transitions.key(5,row['source'],row['target']);plan=plans[key];plant=Plant(Parameters(**plan['parameters']));reports=[];histories=[]
        for step in (.001,.0005):
            proof=replay(plant,plan,dt=step,total=plan['duration']+20,control_period=.004);history=proof.pop('history')
            assert proof['final_stable'] and proof['max_cart']<.96*plant.p.rail and proof['max_force']<=120 and proof['max_force_rate']<=500.000001
            assert np.max(abs(np.asarray(proof['final_state'])[plant.d:]))<.03
            reports.append(dict(step=step,**proof));histories.append(history)
        difference=np.asarray(reports[1]['final_state'])-reports[0]['final_state'];difference[1:plant.d]=wrap(difference[1:plant.d])
        balances=[independent_balance(plant,point[1:-1],point[-1]) for point in histories[0][::5]]
        balance={field:max(r[field] for r in balances) for field in balances[0]}
        assert balance['joint_torque_residual']<1e-8 and balance['cart_force_residual']<1e-8 and balance['power_residual']<1e-8 and balance['energy_difference']<1e-8
        case=dict(source=row['source'],target=row['target'],duration=plan['duration'],reports=reports,final_state_step_difference=float(np.max(abs(difference))),independent_rigid_body_balance=balance)
        cases.append(case);print('CASE_PASS '+json.dumps(case),flush=True)
        fixtures.append(dict(design=analyze(plant,'full_state',target=repository.angles(row['target'])),source_design=analyze(plant,'full_state',target=repository.angles(row['source'])),plan=plan))
    fixture=output/'fixtures.json';fixture.write_text(json.dumps(fixtures),encoding='utf8')
    result=subprocess.run(['node','tests/check-transfers.mjs',str(fixture.relative_to(PROJECT)),str((output/'worker.json').relative_to(PROJECT))],cwd=PROJECT,text=True,capture_output=True,timeout=300)
    assert result.returncode==0,result.stdout+result.stderr
    report=dict(passed=True,checked_at=time.time(),ready_plan_count=len(rows),aggregate=aggregate,samples=cases,checks=['all ready plan hashes, identity, initial state, single scalar input and admission proofs','fresh 1 ms and 0.5 ms RK4 integrations with fixed 4 ms control period, 20 s post-reference hold','independent COM Jacobian Newton balances, passive joint torques, energy and power balance','fresh actual page Worker integrations'],limitations=['default modeled parameters and the certified initial equilibria','no global initial-state or disturbance guarantee','ideal rigid rods without rod self-contact or hardware delay'])
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print('AUDIT_PASS',json.dumps(dict(ready=len(rows),sampled=len(cases),aggregate=aggregate)),flush=True)

if __name__=='__main__':main()
