"""Validated feedback capture, winding-invariant warm starts and cancellation."""
from copy import deepcopy
from pathlib import Path
import time
import numpy as np
from .model import wrap
from .validate_plan import replay
from . import repository,precomputed

ROOT=Path(__file__).resolve().parent.parent


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError('已取消旧规划')


def verify(plant,result,cancel=None,save=False):
    check_cancel(cancel)
    result.update(force_rate=500.,strict_rest=True)
    report=replay(plant,result,total=result['duration']+(20 if plant.n>=4 else 10),cancel=cancel)
    history=report.pop('history')
    passed=bool(report['final_stable'] and report['max_cart']<plant.p.rail*.96 and report['max_tracking_error']<3 and report['max_force']<=plant.p.max_force+1e-6 and report['max_force_rate']<=500+1e-6)
    if passed and save:
        check_cancel(cancel);result['verification']=report
        result['repository_id']=repository.store(result,plant,history)['id']
    return report,passed


def aligned_plan(template,initial,plant,mirror=1):
    """Transform the reference and force, never the true object's current state."""
    data=deepcopy(template);states=np.array(data['states'])*mirror
    derivatives=np.array(data['derivatives'])*mirror
    states[:,0]+=initial[0]-states[0,0]
    offsets=np.round((initial[1:plant.d]-states[0,1:plant.d])/(2*np.pi))*2*np.pi
    states[:,1:plant.d]+=offsets
    data.update(states=states.tolist(),derivatives=derivatives.tolist(),forces=(np.array(data['forces'])*mirror).tolist(),initial=initial.tolist())
    return data


def certified_plan(plant,initial,duration,seed,cancel=None,progress=None,target_angles=None):
    started=time.perf_counter()
    def status(phase,**extra):
        check_cancel(cancel)
        if progress:progress(dict(phase=phase,**extra))
    status('匹配已验证的起摆方案')
    goal=np.zeros(plant.n) if target_angles is None else np.asarray(target_angles)
    ready=precomputed.lookup(plant,initial,goal)
    if ready is not None:
        if ready.get('force_rate')==500:return ready
        report,passed=verify(plant,ready,cancel)
        if passed:ready.update(verification=report);return ready
    for row in reversed(repository.catalog()):
        if row['order']!=plant.n or row['pattern']!=repository.pattern(goal) or row['parameters']!=plant.p.dict() or not row.get('has_control_plan',True):continue
        if np.max(abs(np.asarray(row['initial'])-initial))<1e-12:
            data=repository.read(row['id']);cached=data.get('control_plan')
            if cached and cached.get('force_rate')==500 and data.get('verification',{}).get('final_stable') and data.get('verification',{}).get('max_force_rate',float('inf'))<=500+1e-6:
                cached.update(success=True,wall_seconds=0.,repository_id=row['id'],source='仓库已验证路径')
                return cached
    path=ROOT/'results'/f'verified-{plant.n}.json'
    template=repository.nearest_template(plant,initial,goal)
    if template is None and path.exists():template=__import__('json').loads(path.read_text(encoding='utf8'))
    guess=None
    if template is not None:
        # Different winding numbers describe the same physical posture.
        guess=aligned_plan(template,initial,plant,1)
        delta=initial-np.array(guess['states'][0]);delta[1:plant.d]=wrap(delta[1:plant.d])
        same_physics=all(template['parameters'].get(k)==v for k,v in plant.p.dict().items() if k not in ('max_force','rail'))
        near_hanging=np.max(abs(delta[1:plant.d]))<.20 and np.max(abs(delta[plant.d:]))<.65
        same_target=np.max(abs(wrap(np.array(template.get('target_angles',[0.]*plant.n))-goal)))<1e-9
        if same_physics and near_hanging and same_target:
            for sign in (1,-1):
                status('校验当前初值的闭环起摆',direction=sign)
                candidate=aligned_plan(template,initial,plant,sign)
                if np.max(abs(np.array(candidate['states'])[:,0]))>plant.p.rail*.95:continue
                report,passed=verify(plant,candidate,cancel,save=True)
                if passed:
                    candidate.update(verification=report,success=True,wall_seconds=time.perf_counter()-started,parameters=plant.p.dict(),source='已验证方案 + 当前初值反馈校验',validation='独立闭环重放通过')
                    return candidate
    status('搜索耗散恢复与已验证轨迹的接入点')
    from .recovery import recover_plan
    recovered=recover_plan(plant,initial,goal,cancel,progress)
    if recovered is not None:
        result,history=recovered;check_cancel(cancel)
        result['repository_id']=repository.store(result,plant,history,title='自定义初态恢复 → '+repository.label(repository.pattern(goal)))['id']
        result['wall_seconds']=time.perf_counter()-started
        return result
    # Optimization remains a fallback for states not captured by the library.
    from .optimal import optimize
    budgets=[max(duration,plant.n+2),min(12,max(duration+2,plant.n+4))]
    last=None
    for attempt,horizon in enumerate(budgets):
        status('优化受限起摆路径',search=attempt+1,horizon=horizon,iterations=0)
        nodes=161 if plant.n<=2 else 241 if plant.n==3 else 321 if plant.n==4 else 701
        last=optimize(plant,initial,horizon,nodes,guess,max_iter=420 if plant.n<4 else 550,seed=seed+attempt,
                      cancel=cancel,max_seconds=45,target_angles=goal,progress=lambda i:status('优化受限起摆路径',search=attempt+1,horizon=horizon,iterations=i))
        if not last['success']:
            if last['defect']<.05:guess=last
            continue
        status('独立积分校验，检查落稳与边界',search=attempt+1)
        report,passed=verify(plant,last,cancel,save=True)
        last.update(verification=report,success=passed,parameters=plant.p.dict())
        if passed:
            last.update(wall_seconds=time.perf_counter()-started,validation='独立闭环重放通过')
            return last
        guess=last
    check_cancel(cancel)
    return dict(success=False,recovery=True,wall_seconds=time.perf_counter()-started,
                validation='当前初值的两次受限规划未通过闭环校验；先回中消能，再捕获下垂姿态。')
