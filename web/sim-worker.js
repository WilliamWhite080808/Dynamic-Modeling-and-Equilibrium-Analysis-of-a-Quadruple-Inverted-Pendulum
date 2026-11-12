import {Physics,Estimate,wrap,clamp} from './physics.js';
import {dissipativeForce} from './recovery-policy.js';
import {simulationRate,timelineEnd,STABLE_HOLD_SECONDS} from './experiment.js';
let model,observer,state,time=0,ticks=0,running=true,speed=1,mode='auto',sensor='full_state',kind='ekf';
let force=0,rawForce=0,target=0,stage='balance',plan=null,planStart=0,planning=false,autoRetry=true;
let stepSize=0.001,accumulator=0,last=performance.now(),sent=0,lastPlan=-100,stable=0,attempt=0;
let noise=0,tipUntil=0,tipAmplitude=0,cartUntil=0,cartAmplitude=0,rng=42,boundaries=0,maxForce=0,saturated=0;
let physicsMs=0,controlMs=0,observerMs=0,cycleMs=0,history=[],lastReason='',wantPlan=false,epoch=0;
let settling=false,settleStart=0,recording=[],recordingStride=10,successSent=false;
let forceRate=0,maxForceRate=0,transitionInfo=null;
let trajectory=null,seeking=false,loopRequested=false,seekRequestId=null;
function rememberTrajectory(design,reference,loop=false){
  trajectory={design,reference,initial:[...state],initialForce:force,startTime:time,startTick:ticks,transition:transitionInfo?{...transitionInfo}:null,loop,cycle:0,end:timelineEnd(reference)};
}
function restoreTrajectory(saved,elapsed,resume){
  seeking=true;reset(saved.design,saved.initial);sensor='full_state';mode='auto';noise=0;observer=new Estimate(model,sensor,kind);observer.x=[...state];
  trajectory=saved;time=saved.startTime;ticks=saved.startTick;force=saved.initialForce;rawForce=force;plan=saved.reference;forceRate=plan.force_rate||0;planStart=time;stage='swing';transitionInfo=saved.transition;running=false;
  recording=[[time,...state,force]];
  const steps=Math.round(Math.max(0,Math.min(elapsed,saved.end))/stepSize);
  for(let i=0;i<steps;i++){advance();if(planning||stage==='unprepared')break;}
  seeking=false;running=resume;accumulator=0;last=performance.now();
}
function random(){rng^=rng<<13;rng^=rng>>>17;rng^=rng<<5;return (rng>>>0)/4294967296;}
function normal(){return Math.sqrt(-2*Math.log(Math.max(random(),1e-9)))*Math.cos(2*Math.PI*random());}
function reset(design,initial){
  model=new Physics(design);state=Array(model.dim).fill(0);time=0;ticks=0;force=0;rawForce=0;target=0;stable=0;boundaries=0;maxForce=0;saturated=0;history=[];
  if(initial)state=[...initial];else for(let i=1;i<model.d;i++)state[i]=(i%2?1:-1)*0.025;
  observer=new Estimate(model,sensor,kind,0.015);plan=null;planning=false;attempt=0;lastPlan=-100;stage='balance';lastReason='';accumulator=0;last=performance.now();epoch++;
  settling=false;successSent=false;recordingStride=10;recording=[[0,...state,0]];
  tipUntil=0;tipAmplitude=0;cartUntil=0;cartAmplitude=0;
  forceRate=0;maxForceRate=0;transitionInfo=null;
  trajectory=null;loopRequested=false;seekRequestId=null;
}
function requestPlan(){
  if(sensor!=='full_state'){lastReason='大角度起摆需要全状态测量；部分观测模式仅验证局部稳定。';return;}
  planning=true;stage='planning';attempt++;lastPlan=time;
  postMessage({type:'plan-request',state:[...state],parameters:model.p,pattern:model.target_angles.map(a=>Math.cos(a)>0?'U':'D').join(''),attempt,epoch,time});
}
function control(){
  const t0=performance.now(),s=observer.x,d=model.d;
  const err=[...s];err[0]-=target;for(let i=1;i<d;i++)err[i]=wrap(err[i]-model.target_angles[i-1]);
  const angle=Math.max(...err.slice(1,d).map(Math.abs)),velocity=Math.max(...err.slice(d+1).map(Math.abs));
  const local=angle<0.3&&velocity<3.0;
  if(mode==='off'){rawForce=0;stage='free';}
  else if(plan){
    const elapsed=time-planStart;
    if(elapsed>=plan.duration){plan=null;stage='balance';}
    else{
      let active=plan,localTime=elapsed,kind='track';
      if(plan.segments)for(let j=0;j<plan.segments.length;j++){
        const segment=plan.segments[j];
        if(localTime<segment.duration-1e-10||j===plan.segments.length-1){active=segment.plan||segment;kind=segment.kind;localTime=Math.max(0,Math.min(localTime,segment.duration));break;}
        localTime=Math.max(0,localTime-segment.duration);
      }
      if(kind==='dissipate'){rawForce=dissipativeForce(s,localTime,model.p,active.policy);stage='dissipate';}
      else if(kind==='balance'){const captureError=[...err];captureError[0]=s[0]-(plan.target_position||0);rawForce=-model.K.reduce((u,k,i)=>u+k*captureError[i],0);stage='balance';}
      else{
      const z=localTime/active.dt,k=Math.min(Math.floor(z),active.states.length-2),a=z-k;
      const ref=active.states[k].map((v,i)=>active.derivatives?(2*a**3-3*a*a+1)*v+(a**3-2*a*a+a)*active.dt*active.derivatives[k][i]+(-2*a**3+3*a*a)*active.states[k+1][i]+(a**3-a*a)*active.dt*active.derivatives[k+1][i]:v*(1-a)+active.states[k+1][i]*a);
      const K=active.gains[k].map((v,i)=>v*(1-a)+active.gains[k+1][i]*a);
      const deviation=s.map((v,i)=>i>0&&i<d?wrap(v-ref[i]):v-ref[i]);
      rawForce=active.forces[k]*(1-a)+active.forces[k+1]*a-K.reduce((v,k,i)=>v+k*deviation[i],0);
      stage='swing';
      const weighted=deviation.reduce((s,v,i)=>s+v*v*(i<d?1:0.025),0);
      if(weighted>3.0){plan=null;lastReason='起摆轨迹偏离，自动重新规划';stage='recover';}
      }
    }
  }
  if(mode!=='off'&&!plan){
    if(local||mode==='lqr'){
      rawForce=-model.K.reduce((u,k,i)=>u+k*err[i],0);stage='balance';
    }else{
      stage=settling?'settle':'recover';
      // Dissipative cart force until replanning. No torque is injected at joints.
      rawForce=-12*s[0]-10*s[d];
      const hanging=Math.max(...s.slice(1,d).map(v=>Math.abs(wrap(v-Math.PI))))<.12;
      const quiet=Math.max(...s.slice(d).map(Math.abs))<.4&&Math.abs(s[0])<.45;
      const pulseFinished=time+1e-10>=tipUntil&&time+1e-10>=cartUntil;
      if(autoRetry&&mode==='auto'&&pulseFinished&&time-lastPlan>1.5&&(!settling||(hanging&&quiet)||time-settleStart>22))requestPlan();
    }
  }
  if(!plan&&Math.abs(s[0])>model.p.rail*0.78){
    const sign=Math.sign(s[0]),outward=Math.max(0,sign*s[d]);
    const brake=sign*(65*(Math.abs(s[0])-model.p.rail*0.78)+18*outward);
    rawForce-=brake;
  }
  const previousForce=force;force=clamp(rawForce,-model.p.max_force,model.p.max_force);
  if(forceRate)force=clamp(force,previousForce-forceRate*stepSize*4,previousForce+forceRate*stepSize*4);
  maxForceRate=Math.max(maxForceRate,Math.abs(force-previousForce)/(stepSize*4));
  maxForce=Math.max(maxForce,Math.abs(force));if(Math.abs(rawForce)>model.p.max_force)saturated++;
  controlMs=performance.now()-t0;
}
function advance(){
  if(!model||planning||stage==='unprepared')return;
  const t0=performance.now();
  if(ticks%4===0){
    const ot=performance.now(),y=model.measure(state,sensor).map(v=>v+noise*normal());
    observer.update(y,force,stepSize*4,noise);observerMs=performance.now()-ot;
    if(!observer.x.every(Number.isFinite)||observer.x.some(v=>Math.abs(v)>1e6)){running=false;lastReason='观测器发散，已停止摆动；请复位或调整传感器。';return;}
    control();
  }
  if(planning)return;
  const pt=performance.now();
  const applied=clamp(force+(time<cartUntil?cartAmplitude:0),-model.p.max_force,model.p.max_force);
  state=model.step(state,applied,stepSize,time<tipUntil?tipAmplitude:0);
  if(model.contact(state)){boundaries++;if(plan){plan=null;stage='recover';lastReason='碰触轨道端部，已按质量矩阵施加接触冲量';}}
  physicsMs=performance.now()-pt;
  if(!state.every(Number.isFinite)||state.some(v=>Math.abs(v)>1e6)){running=false;lastReason='数值异常，仿真已停止摆动；状态未被重置。';return;}
  time+=stepSize;ticks++;
  if(ticks%recordingStride===0){recording.push([time,...state,applied]);if(recording.length>6000){recording=recording.filter((_,i)=>i%2===0);recordingStride*=2;}}
  const maxAngle=Math.max(...state.slice(1,model.d).map((v,i)=>Math.abs(wrap(v-model.target_angles[i]))));
  if(maxAngle<0.5*Math.PI/180&&Math.max(...state.slice(model.d).map(Math.abs))<0.03&&Math.abs(state[0]-target)<0.03)stable+=stepSize;else stable=0;
  if(stable>=2&&!successSent){successSent=true;if(!seeking)postMessage({type:'success-captured',epoch,parameters:model.p,target_angles:model.target_angles,frames:recording.map(r=>[...r]),sample_dt:stepSize*recordingStride,settled_at:time-stable,target});}
  if(stable===0&&successSent){successSent=false;}
  if(ticks%50===0){history.push([time,state[0],...state.slice(1,model.d),applied,model.energy(state),Math.hypot(...state.map((v,i)=>v-observer.x[i]))]);if(history.length>2400)history.shift();}
  cycleMs=performance.now()-t0;
  if(!seeking&&trajectory?.loop&&stable>=STABLE_HOLD_SECONDS&&Math.max(...state.slice(model.d).map(Math.abs))<.03)loopRequested=true;
}
function snapshot(){if(!model)return;postMessage({type:'state',state:[...state],estimate:[...observer.x],time,force,rawForce,target,stage,planning,running,speed,stable,attempt,boundaries,maxForce,maxForceRate,forceRate,transition:transitionInfo,plan_active:!!plan,timeline:trajectory?{time:time-trajectory.startTime,end:trajectory.end,cycle:trajectory.cycle,loop:trajectory.loop}:null,seek_request_id:seekRequestId,saturation:ticks?saturated/(ticks/4):0,energy:model.energy(state),physicsMs,controlMs,observerMs,cycleMs,lag:accumulator,reason:lastReason,epoch,history:history.slice(-2)});}
onmessage=e=>{
  const m=e.data;
  if(m.type==='init'){
    sensor=m.sensor||sensor;kind=m.observer||kind;mode=m.mode||mode;reset(m.design,m.initial);running=true;
    if(m.precomputedPlan&&sensor==='full_state'&&mode==='auto'){
      plan=m.precomputedPlan;forceRate=plan.force_rate||0;planStart=0;stage='swing';lastReason='已加载离线预优化方案 · 小车力反馈跟踪中';
      rememberTrajectory(m.design,plan,!!m.loop);
    }else if(m.requirePrecomputed&&mode==='auto'&&!(Math.max(...state.slice(1,model.d).map((a,i)=>Math.abs(wrap(a-model.target_angles[i]))))<1e-8&&Math.max(...state.slice(model.d).map(Math.abs))<1e-8)){
      running=false;stage='unprepared';lastReason='该参数与目标的悬垂方案尚未预优化完成，保持下垂等待；不会现场启动优化。';
    }
    snapshot();
  }
  if(!model&&m.type!=='play-transition')return;
  if(m.type==='play-transition'){
    if(!m.plan?.success||!m.plan.transition||m.design.parameters.n>5)return;
    // Explicit point-and-play: the user authorizes loading the recorded start.
    // This is separate from continuous, state-preserving tour transitions.
    sensor='full_state';mode='auto';noise=0;reset(m.design,m.plan.initial);
    observer.x=[...state];plan=m.plan;forceRate=plan.force_rate||0;planStart=0;
    stage='swing';running=true;stable=0;transitionInfo={...plan.transition,start_time:0,duration:plan.duration};
    rememberTrajectory(m.design,plan,!!m.loop);
    lastReason=`已跳转到起点 ${plan.transition.source.replaceAll('U','↑').replaceAll('D','↓')}，正在执行稳态转换`;
    postMessage({type:'transition-started',transition:transitionInfo,jumped:true,request_id:m.request_id,epoch,time});
  }
  if(m.type==='transition'){
    const source=m.plan?.transition?.source;
    const observed=state.slice(1,model.d).map(a=>Math.cos(a)>0?'U':'D').join('');
    const near=source&&Math.max(...state.slice(1,model.d).map((a,i)=>Math.abs(wrap(a-(source[i]==='U'?0:Math.PI)))))<.025;
    const samePlant=m.design&&Object.entries(model.p).every(([key,value])=>m.design.parameters[key]===value);
    if(!m.plan?.success||model.n>5||!samePlant||planning||plan||!near||observed!==source||Math.abs(state[0])>.05||Math.max(...state.slice(model.d).map(Math.abs))>.06){
      postMessage({type:'transition-rejected',request_id:m.request_id,message:'请先让所选起点稳态回中并停稳，再开始转场。'});return;
    }
    // Only the controller/reference changes. No state, time, tick or camera epoch reset.
    model=new Physics(m.design);sensor='full_state';observer=new Estimate(model,sensor,kind);observer.x=[...state];
    mode='auto';noise=0;target=0;plan=m.plan;forceRate=plan.force_rate||0;planStart=time;stage='swing';planning=false;settling=false;running=true;stable=0;
    transitionInfo={...plan.transition,start_time:time,duration:plan.duration};maxForceRate=0;
    rememberTrajectory(m.design,plan,!!m.loop);
    successSent=false;recordingStride=10;recording=[[time,...state,force]];
    lastReason=`稳态直接转场 ${source.replaceAll('U','↑').replaceAll('D','↓')} → ${plan.transition.target.replaceAll('U','↑').replaceAll('D','↓')} · 不复位`;
    postMessage({type:'transition-started',transition:transitionInfo,request_id:m.request_id,epoch,time});
  }
  if(m.type==='settings'){
    if(m.running!==undefined&&stage!=='unprepared')running=m.running;if(m.speed!==undefined)speed=simulationRate(m.speed,speed);if(m.loop!==undefined&&trajectory)trajectory.loop=!!m.loop;if(m.mode!==undefined&&m.mode!==mode){mode=m.mode;plan=null;trajectory=null;planning=false;settling=false;epoch++;if(stage==='unprepared'&&mode!=='auto'){stage='free';running=true;}}
    if(m.sensor||m.observer){sensor=m.sensor||sensor;kind=m.observer||kind;observer=new Estimate(model,sensor,kind,0.02);plan=null;}
    if(m.noise!==undefined)noise=m.noise;if(m.target!==undefined)target=clamp(m.target,-model.p.rail*0.6,model.p.rail*0.6);
    if(m.autoRetry!==undefined)autoRetry=m.autoRetry;if(m.stepSize)stepSize=m.stepSize;
  }
  if(m.type==='seek'&&trajectory){
    const saved=trajectory;restoreTrajectory(saved,m.time,!!m.running);seekRequestId=m.request_id;
    lastReason='已按真实动力学重新计算到指定时刻';postMessage({type:'seek-complete',request_id:m.request_id,time:time-saved.startTime,epoch,signals:recording.map(r=>({time:r[0],state:r.slice(1,-1),force:r.at(-1),energy:model.energy(r.slice(1,-1))}))});
  }
  if(m.type==='step'&&!planning){const keep=running;running=false;advance();snapshot();}
  if(m.type==='impulse'){tipAmplitude=m.tip||0;tipUntil=time+0.12;cartAmplitude=m.cart||0;cartUntil=time+0.12;}
  if(m.type==='plan-now'&&!planning)requestPlan();
  if(m.type==='plan-result'&&m.epoch===epoch){
    planning=false;
    if(m.plan?.success){plan=m.plan;forceRate=plan.force_rate||0;transitionInfo=null;planStart=time;stage='swing';settling=false;rememberTrajectory(model,plan,!!m.loop);lastReason=`起摆方案就绪 · ${m.plan.wall_seconds.toFixed(1)} s 校验 · 反馈跟踪中`;}
    else{plan=null;lastPlan=time;settling=true;settleStart=time;stage='settle';lastReason=m.error||m.plan?.validation||'当前起摆未通过校验：先回中消能，捕获下垂姿态后再起摆。';}
  }
  if(m.type==='export')postMessage({type:'export',history,parameters:model.p,state,seed:rng,stepSize});
  last=performance.now();snapshot();
};
setInterval(()=>{
  const now=performance.now(),elapsed=(now-last)/1000;last=now;
  if(running&&!planning&&model){
    accumulator+=elapsed*speed;
    const budget=performance.now();let count=0;
    // Retain debt. Never enlarge dt or silently throw away simulation steps.
    while(accumulator>=stepSize&&count<150&&performance.now()-budget<12){advance();accumulator-=stepSize;count++;if(loopRequested&&trajectory){const saved=trajectory,heldFor=stable;saved.cycle++;restoreTrajectory(saved,0,true);lastReason='稳定保持 10 秒，开始下一次起摆';postMessage({type:'trajectory-restarted',transition:transitionInfo,cycle:saved.cycle,held_for:heldFor,epoch});break;}if(planning||!running)break;}
  }else accumulator=0;
  // Feed a 120 Hz display with fresh physical states, independently of UI text.
  if(now-sent>=8){snapshot();sent=now;}
},4);
