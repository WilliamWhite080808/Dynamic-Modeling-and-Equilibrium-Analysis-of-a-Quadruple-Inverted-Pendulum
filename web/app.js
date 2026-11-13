import {wrap,clamp} from './physics.js';
import {Renderer} from './render.js';
import {ReplayPlayer,saveSuccess} from './replay.js';
import {patternsFor,equilibriaFor} from './targets.js';
import {eulerTour,poseArrows} from './transfers.js';
import {TelemetryDashboard} from './telemetry.js';
import {simulationRate,timelineEnd,STABLE_HOLD_SECONDS} from './experiment.js';
import {CoreRecorder} from './recorder.js';
const $=id=>document.getElementById(id), colors=Array.from({length:20},(_,i)=>['#3478ef','#f2a13c','#19ab9a','#a275df','#e6719b','#368bba','#b79437','#668356'][i%8]);
const labels=['','单','双','三','四','五','六','七','八','九','十'], english=['','SINGLE','DOUBLE','TRIPLE','QUADRUPLE','QUINTUPLE','SIX-LINK','SEVEN-LINK','EIGHT-LINK','NINE-LINK','TEN-LINK'];
const worker=new Worker('/sim-worker.js?v=experiment-4',{type:'module'});
const renderer=new Renderer($('arena'));
const player=new ReplayPlayer();
const telemetry=new TelemetryDashboard($('telemetry-dashboard'));
const recorder=new CoreRecorder(document.querySelector('.stage-grid'),$('record-core'),message=>setNotice(message));
let seekDragging=false,seekWasRunning=false,seekTimer=null,seekSerial=0,pendingSeek=null,lastSeekSent=0;
let lastPlayback=null,workerReasonSeen='';
const clientId=(()=>{try{const id=sessionStorage.getItem('pendulum-client-id')||crypto.randomUUID();sessionStorage.setItem('pendulum-client-id',id);return id;}catch{return crypto.randomUUID();}})();
let activeJob=null,replayActive=false,liveContext=null,liveSnapshot=null,replayFrame=0;
let goalPattern='UUU',inventoryGroups=[],selectedCard=null,selectedTarget='UUU';
let bankRows=[],bankTotal=null;
let transferBank=null,transferBusy=false,transferToken=0,pendingTransfer=null,activeTransfer=null,cruise=null,transferOrder=0,transferSummary='';
let transferRunIntent=true;
const goalChoices=order=>order<=20?equilibriaFor(order):patternsFor(order);
const equilibriumCode=angles=>angles.map(a=>Math.cos(a)>0?'U':'D').join('');
const targetLabel=code=>[...code].map(c=>c==='U'?'上':'下').join(' / ');
const requestedOrder=Number(new URLSearchParams(location.search).get('order'));
let n=Number.isInteger(requestedOrder)&&requestedOrder>=1&&requestedOrder<=20?requestedOrder:3,design=null,snapshot=null,showTrail=true,activePreset='near',generation=0;
let showHidden=false,showGhost=false,running=true,lastUI=0,runCommand=null;
const parameters={n:3,cart_mass:1.5,length:0.65,mass:0.3,gravity:9.81,damping:0.006,cart_damping:0.08,max_force:120,rail:2.4,point_mass:false};
const rad=Math.PI/180, deg=180/Math.PI;
function settings(values){if(values.running!==undefined)runCommand=values.running;worker.postMessage({type:'settings',...values});}
function setNotice(text,warn=false){$('notice').classList.toggle('warn',warn);$('notice').lastElementChild.textContent=text;}
function loading(title,message){$('loading').classList.remove('hidden');$('loading').querySelector('h3').textContent=title;$('loading').querySelector('p').textContent=message;}
function seeded(){let s=42;return()=>{s^=s<<13;s^=s>>>17;s^=s<<5;return (s>>>0)/4294967296;};}
let random=seeded();
function initialFor(preset){
  const x=Array(2*(n+1)).fill(0);
  for(let i=1;i<=n;i++)x[i]=preset==='down'?Math.PI:preset==='random'?(random()*2-1)*Math.PI:0.012;
  return x;
}
function goalOptions(order,preferred=$('goal').value){
  const options=goalChoices(order),value=options.includes(preferred)?preferred:options[0];
  $('goal').innerHTML=options.map(code=>`<option value="${code}">${targetLabel(code)}</option>`).join('');$('goal').value=value;
  return value;
}
async function initialize(preset='down',custom=null){
  pendingSeek=null;seekDragging=false;clearTimeout(seekTimer);workerReasonSeen='';
  transferToken++;transferBusy=false;pendingTransfer=null;activeTransfer=null;cruise=null;transferOrder=0;transferSummary='';transferRunIntent=true;
  if(replayActive){const order=n,p={...parameters},goal=$('goal').value;exitReplay();n=order;Object.assign(parameters,p);$('force').value=p.max_force;goalOptions(order,goal);}
  cancelPlanning();settings({running:false});
  const gen=++generation;activePreset=preset;
  loading(preset==='down'?'加载离线预优化方案':'正在建立系统',`建立 ${n} 重刚性杆动力学与 ${2*(n+1)} 维控制器`);
  $('orders').querySelectorAll('button').forEach(b=>{b.classList.toggle('selected',+b.dataset.order===n);b.disabled=true;});
  try{
    parameters.n=n;parameters.max_force=+$('force').value;
    goalPattern=goalOptions(n);
    if(preset==='down'&&transferBank?.plugin_mode){
      const from='D'.repeat(n),available=transferBank.entries.filter(row=>row.order===n&&row.source===from&&row.status==='ready');
      if(!available.some(row=>row.target===goalPattern)&&available.length)goalPattern=goalOptions(n,available[0].target);
    }
    if(goalPattern.includes('D')||preset==='down')$('sensor').value='full_state';
    $('goal').disabled=false;$('sensor').disabled=goalPattern.includes('D');
    const initial=custom||initialFor(preset);
    const exactHanging=Math.abs(initial[0])<1e-10&&initial.slice(n+1).every(v=>Math.abs(v)<1e-10)&&initial.slice(1,n+1).every(v=>Math.abs(wrap(v-Math.PI))<1e-10);
    if(exactHanging)$('sensor').value='full_state';
    const response=await fetch('/api/design',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parameters,sensor:$('sensor').value,pattern:goalPattern,initial})});
    if(!response.ok)throw Error(await response.text());
    const data=await response.json();if(gen!==generation)return;const readyPlan=data.hanging_plan;bankRows=data.precomputed_catalog.entries;delete data.hanging_plan;delete data.precomputed_catalog;design=data;
    worker.postMessage({type:'init',design,initial,sensor:$('sensor').value,observer:$('observer').value,mode:$('controller').value,precomputedPlan:readyPlan,requirePrecomputed:preset==='down'||exactHanging,loop:true});
    settings({running:true,mode:$('controller').value,noise:+$('noise').value,speed:+$('speed').value,stepSize:+$('dt').value,autoRetry:$('retry').checked});
    running=true;$('pause').textContent='停止摆动';renderer.trail=[];snapshot=null;
    $('replay-hint').textContent='当前实验成功后会自动保存；已有记录可随时轨迹复现';
    $('dimension').textContent=`${2*(n+1)} 维状态`;$('order-title').textContent=(labels[n]||n)+'重倒立摆';$('order-label').textContent=english[n]||`${n}-LINK`;
    $('orders').querySelectorAll('button').forEach(b=>b.disabled=false);
    ['near','down','random'].forEach(p=>$(`${p}`).classList.toggle('active',p===preset));
    $('legend').innerHTML=Array.from({length:n},(_,i)=>`<span><i style="background:${colors[i]}"></i>θ${i+1}</span>`).join('');
    $('left-rail').textContent=parameters.rail.toFixed(1);$('right-rail').textContent=parameters.rail.toFixed(1);
    $('target').value=0;$('target-value').textContent='0.00 m';
    buildAnalysis();
    $('duration').value=String(n+2);telemetry.clear();
    const health=data.observability;
    setNotice(health.condition>1e9?'当前传感配置数值上接近不可观：请检查系统分析，并降低扰动或更换传感器。':'RK4 1 ms · 控制 250 Hz · 渲染与物理解耦。可以试着推它一下。',health.condition>1e9);
    updateBankStatus();
    if(n<=20&&preset==='down'){
      await refreshTransfers();if(gen!==generation)return;
      fillTransferOptions('D'.repeat(n),goalPattern);
      if(transferCompatible(transferRow($('transfer-from').value,$('transfer-to').value)))playTransfer($('transfer-from').value,$('transfer-to').value);
    }
  }catch(err){if(gen!==generation)return;loading('系统建立失败',String(err));setNotice('无法连接本机求解服务，请通过 python -m triple_pendulum.server 启动。',true);$('orders').querySelectorAll('button').forEach(b=>b.disabled=false);}
}
function cancelPlanning(){const id=activeJob;activeJob=null;if(id)fetch(`/api/plan/${id}`,{method:'DELETE'}).catch(()=>{});}
async function solvePlan(message){
  if(transferBusy||pendingTransfer)return;
  const gen=generation,id=crypto.randomUUID();activeJob=id;let ticks=0;
  if(!replayActive)loading('正在寻找起摆路径',`第 ${message.attempt} 次尝试 · 仿真时钟已停止 · 推力与轨道约束保持启用`);
  setNotice('正在校验当前初值的恢复与起摆路径；通过后继续积分，不重置摆角。');
  try{
    const response=await fetch('/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...message,duration:+$('duration').value,seed:42+message.attempt,client_id:clientId,request_id:id})});
    if(!response.ok)throw Error(await response.text());
    await response.json();
    if(gen!==generation||activeJob!==id){fetch(`/api/plan/${id}`,{method:'DELETE'}).catch(()=>{});return;}
    while(gen===generation&&activeJob===id){
      const result=await (await fetch(`/api/plan/${id}`)).json();
      if(result.status==='done'){
        worker.postMessage({type:'plan-result',epoch:message.epoch,plan:result.plan,loop:true});
        if(!replayActive)$('loading').classList.add('hidden');
        if(result.plan.success){setNotice(`路径已通过独立验证并存入仓库；正在实时跟踪目标 ${targetLabel(message.pattern||'U'.repeat(n))}。`);refreshInventoryCount();}
        return;
      }
      if(result.status==='error')throw Error(result.error);
      if(result.status==='cancelled')return;
      if(!replayActive)$('loading').querySelector('p').textContent=`${result.phase||'正在求解'} · ${Math.round(result.elapsed||ticks*.8)} s${result.iterations?' · '+result.iterations+' 次迭代':''} · 可切换阶数取消`;
      ticks++;await new Promise(resolve=>setTimeout(resolve,800));
    }
  }catch(err){if(gen===generation&&activeJob===id){worker.postMessage({type:'plan-result',epoch:message.epoch,error:`本轮搜索结束，先回中消能再重试：${String(err).slice(0,100)}`});if(!replayActive)$('loading').classList.add('hidden');}}
  finally{if(activeJob===id)activeJob=null;}
}
worker.onmessage=e=>{
  const m=e.data;
  if(m.type==='trajectory-restarted'){
    if(m.transition)activeTransfer={...m.transition};
    telemetry.clear();renderer.reset();setNotice(`已稳定保持 ${STABLE_HOLD_SECONDS} 秒，开始第 ${m.cycle+1} 次起摆。`);return;
  }
  if(m.type==='seek-complete'){
    if(m.request_id!==pendingSeek)return;
    pendingSeek=null;telemetry.clear();if(m.signals)telemetry.buffer.rows=m.signals;renderer.reset();return;
  }
  if(m.type==='transition-started'){
    const result=pendingTransfer;if(!result||result.request_id!==m.request_id)return;
    design=result.design;goalPattern=result.target;goalOptions(n,result.target);
    $('controller').value='auto';$('sensor').value='full_state';$('sensor').disabled=result.target.includes('D');$('noise').value=0;$('noise-value').textContent='0.000';$('target').value=0;$('target-value').textContent='0.00 m';
    if(m.jumped){telemetry.clear();sceneLabels();$('orders').querySelectorAll('button').forEach(b=>b.disabled=false);lastPlayback={order:n,source:result.source,target:result.target};}
    running=transferRunIntent;settings({running});$('pause').textContent=running?'停止摆动':'继续摆动';fillTransferOptions(result.source,result.target);
    activeTransfer={...m.transition,waypoints:pendingTransfer.plan.route_waypoints};pendingTransfer=null;transferBusy=false;buildAnalysis();updateBankStatus();renderTransferMatrix();
    setNotice(`${m.jumped?'已切换到初态，开始运动':'连续转换'}：${poseArrows(m.transition.source)} → ${poseArrows(m.transition.target)}`);
    return;
  }
  if(m.type==='transition-rejected'){if(m.request_id!==pendingTransfer?.request_id)return;transferBusy=false;pendingTransfer=null;cruise=null;goalOptions(n,equilibriumCode(design.target_angles));setNotice(m.message,true);return;}
  if(m.type==='plan-request'){solvePlan(m);return;}
  if(m.type==='export'){exportData(m);return;}
  if(m.type==='success-captured'){captureSuccess(m);return;}
  if(m.type!=='state')return;
  if(pendingSeek!==null&&m.seek_request_id!==pendingSeek)return;
  liveSnapshot=m;if(replayActive)return;telemetry.push(m);
  if(runCommand!==null&&m.running===runCommand)runCommand=null;
  if(runCommand===null&&!transferBusy&&!seekDragging)running=m.running;
  snapshot=m;
  if(!m.planning)$('loading').classList.add('hidden');
  if(m.reason&&m.reason!==workerReasonSeen){workerReasonSeen=m.reason;setNotice(m.reason,m.stage==='recover'||!m.running);}
};
worker.onerror=e=>{loading('实时线程停止',e.message);setNotice('实时求解线程发生错误，请重新建立实验。',true);};

function canvasSize(canvas){const r=canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);if(canvas.width!==Math.round(r.width*dpr)||canvas.height!==Math.round(r.height*dpr)){canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);}const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);return [c,r.width,r.height];}
function rounded(c,x,y,w,h,r=5){c.beginPath();c.roundRect(x,y,w,h,r);}
let arenaGeometry=null;
function drawArena(){
  arenaGeometry=renderer.draw({design,snapshot,hidden:showHidden,ghost:showGhost,trail:showTrail});
}

function updateUI(now){
  if(!snapshot||!design)return;
  const s=snapshot,d=n+1,a=Math.max(...s.state.slice(1,d).map((v,i)=>Math.abs(wrap(v-(design.target_angles?.[i]||0)))))*deg;
  const number=(id,x,unit,digits)=>$(id).innerHTML=`${x.toFixed(digits)}<small>${unit}</small>`;
  number('angle-metric',a,'°',2);number('position-metric',s.state[0],'m',2);number('force-metric',s.force,'N',1);number('stable-metric',s.stable,'s',1);
  const status=replayActive?'成功轨迹复现':s.stage==='unprepared'?'等待预优化':s.planning?'规划起摆':!s.running?'已停止摆动':s.stage==='dissipate'?'消能回中':s.stage==='free'?'自由运动':s.stage==='settle'?'回中消能':s.stage==='recover'?'失衡 · 重试':s.stage==='swing'?'起摆跟踪':s.stable>=1?'已稳定':'闭环稳摆';
  $('status').textContent=status;$('status').classList.toggle('warn',s.planning||s.stage==='recover'||s.stage==='free');
  $('canvas-mode').textContent=replayActive?'RECORDED TRAJECTORY / 真实记录':s.stage==='dissipate'?'DISSIPATIVE RECOVERY':s.stage==='unprepared'?'AWAITING OFFLINE PLAN':s.planning?'PLANNING / 时钟停止':s.stage==='swing'?'SWING-UP / TVLQR':s.stage==='free'?'OPEN LOOP':'CLOSED LOOP / LQR';
  $('canvas-message').textContent=s.stage==='dissipate'?'只用小车力消能 · 随后接入起摆路径':s.stage==='unprepared'?'离线方案尚未就绪 · 保持下垂静止':s.planning?`第 ${s.attempt} 次受限规划`:s.stage==='swing'?'只施加小车水平力 · 反馈跟踪':s.stable>1?'平衡已捕获 · 等待你的挑战':s.stage==='recover'?'超出局部稳定域 · 尝试恢复':'目标误差 '+(Math.abs(s.state[0]-s.target)*100).toFixed(1)+' cm';
  $('clock').textContent=`${Math.floor(s.time/60).toString().padStart(2,'0')}:${(s.time%60).toFixed(2).padStart(5,'0')}`;
  $('energy').textContent=s.energy.toFixed(3);$('physics-ms').textContent=s.physicsMs.toFixed(3);$('observer-ms').textContent=s.observerMs.toFixed(3);
  $('contacts').textContent=s.boundaries;$('saturation').textContent=`饱和率 ${(s.saturation*100).toFixed(1)}%`;
  const error=Math.hypot(...s.state.map((v,i)=>i>0&&i<d?wrap(v-s.estimate[i]):v-s.estimate[i]));$('estimate-error').textContent=error.toExponential(1);
  $('realtime-status').textContent=s.planning?'规划中 · 仿真时钟已停止':s.lag>.15?`计算落后 ${s.lag.toFixed(2)} s`:`${s.speed}× / ${s.running?'实时运行':'已停止摆动'}`;
  updateExperimentTimeline(s);
  updateTransferUI(s);
  if(replayActive){$('canvas-message').textContent=player.clip.source+' · '+(player.playing?'正在轨迹复现':'已停止摆动');$('realtime-status').textContent='轨迹复现模式 · 实时实验已停止摆动';$('replay-time').textContent=`${player.time.toFixed(2)} / ${player.duration.toFixed(2)} s`;$('replay-seek').value=String(player.time);$('replay-toggle').textContent=player.playing?'停止摆动':'继续摆动';$('pause').textContent=player.playing?'停止摆动':'继续摆动';}
  else $('pause').textContent=running?'停止摆动':'继续摆动';

  if($('settings-dialog').open&&$('analysis').parentElement.open){
    $('state-table').innerHTML=`<table><thead><tr><th>状态</th><th>真实角度 / °</th><th>估计角度 / °</th><th>角速度 / °/s</th></tr></thead><tbody>${Array.from({length:n},(_,i)=>`<tr><td style="color:${colors[i]}">θ${i+1}</td><td>${(wrap(s.state[i+1])*deg).toFixed(3)}</td><td>${(wrap(s.estimate[i+1])*deg).toFixed(3)}</td><td>${(s.state[d+i+1]*deg).toFixed(3)}</td></tr>`).join('')}</tbody></table>`;
  }
}
function buildAnalysis(){
  const c=design.controllability,o=design.observability;
  $('health').innerHTML=[['可控秩',`${c.rank} / ${design.K.length}`],['可控条件数',c.condition.toExponential(2)],['可观秩',`${o.rank} / ${design.K.length}`],['可观条件数',o.condition.toExponential(2)],['可观最小奇异值',o.sigma_min.toExponential(2)],['力输入数','1 · 小车']].map(([a,b])=>`<div><span>${a}</span><b>${b}</b></div>`).join('');
}
function drawPoles(){
  if(!design||!$('settings-dialog').open||!$('analysis').parentElement.open)return;
  const [c,w,h]=canvasSize($('poles'));c.clearRect(0,0,w,h);const vals=[...design.open_poles,...design.closed_poles],range=Math.max(...vals.map(p=>Math.abs(p[0])),...vals.map(p=>Math.abs(p[1])),1)*1.15;
  const x=v=>w/2+v/range*(w/2-17),y=v=>h/2-v/range*(h/2-12);
  c.strokeStyle='#405349';c.lineWidth=1;c.beginPath();c.moveTo(12,h/2);c.lineTo(w-12,h/2);c.moveTo(w/2,5);c.lineTo(w/2,h-5);c.stroke();
  c.font='8px Consolas';c.fillStyle='#6d8c79';c.fillText('−'+range.toFixed(0),12,h/2+13);c.fillText('+'+range.toFixed(0),w-28,h/2+13);
  for(const p of design.open_poles){c.strokeStyle=colors[1];const a=x(p[0]),b=y(p[1]);c.beginPath();c.moveTo(a-3,b-3);c.lineTo(a+3,b+3);c.moveTo(a+3,b-3);c.lineTo(a-3,b+3);c.stroke();}
  for(const p of design.closed_poles){c.fillStyle=colors[0];c.beginPath();c.arc(x(p[0]),y(p[1]),2.5,0,Math.PI*2);c.fill();}
}
function animate(now){if(replayActive){player.advance(Math.min((now-replayFrame)/1000,.1));snapshot=player.snapshot();}replayFrame=now;drawArena();telemetry.recording=recorder.recording;telemetry.draw(now,snapshot?{...snapshot,rail:parameters.rail,forceLimit:parameters.max_force}:null,replayActive);recorder.frame(now);if(now-lastUI>100){updateUI(now);drawPoles();lastUI=now;}requestAnimationFrame(animate);}
requestAnimationFrame(animate);

$('orders').addEventListener('click',e=>{const order=+e.target.dataset.order;if(order){if(replayActive)exitReplay();n=order;const url=new URL(location.href);url.searchParams.set('order',order);globalThis.history.replaceState(null,'',url);initialize('down');}});
['near','down','random'].forEach(p=>$(p).onclick=()=>initialize(p));$('reset').onclick=()=>{if(lastPlayback?.order===n&&n<=20)playTransfer(lastPlayback.source,lastPlayback.target);else initialize('down');};
$('pause').onclick=()=>{if(replayActive){player.playing=!player.playing;return;}if(snapshot?.stage==='unprepared'){initialize('down');return;}running=!running;if(transferBusy)transferRunIntent=running;settings({running});$('pause').textContent=running?'停止摆动':'继续摆动';};
$('step').onclick=()=>{if(replayActive){player.playing=false;player.seek(player.time+player.clip.sample_dt);return;}running=false;if(transferBusy)transferRunIntent=false;settings({running:false});worker.postMessage({type:'step'});$('pause').textContent='继续摆动';};
$('controller').onchange=()=>{cancelPlanning();settings({mode:$('controller').value});};
function setSimulationRate(value,writeInput=true){const rate=simulationRate(value,1);if(writeInput)$('speed').value=String(rate);$('speed-range').value=String(rate);$('speed-label').textContent=`${+rate.toFixed(3)}×`;if(replayActive)player.speed=rate;else settings({speed:rate});}
$('speed').onchange=()=>setSimulationRate($('speed').value);
$('speed').oninput=()=>{const value=+$('speed').value;if($('speed').value!==''&&value>=.1&&value<=10)setSimulationRate(value,false);};
$('speed-range').oninput=()=>setSimulationRate($('speed-range').value);
$('speed-default').onclick=()=>setSimulationRate(1);
$('speed-toggle').onclick=()=>{const open=$('speed-panel').classList.toggle('hidden');$('speed-toggle').setAttribute('aria-expanded',String(!open));};
document.addEventListener('pointerdown',e=>{if(!e.target.closest('.rate-control')){$('speed-panel').classList.add('hidden');$('speed-toggle').setAttribute('aria-expanded','false');}});
function updateExperimentTimeline(s){
  const timeline=replayActive?{time:player.time,end:timelineEnd({duration:player.duration,verification:{settled_at:player.clip.settled_at-player.offset}})}:s.timeline;
  $('experiment-seek').disabled=!timeline||transferBusy;
  if(!timeline)return;
  $('experiment-seek').max=String(timeline.end);
  if(!seekDragging&&pendingSeek===null)$('experiment-seek').value=String(Math.min(timeline.time,timeline.end));
  const shown=seekDragging||pendingSeek!==null?+$('experiment-seek').value:Math.min(timeline.time,timeline.end);
  $('experiment-time').textContent=`${shown.toFixed(2)} / ${timeline.end.toFixed(2)} s`;
}
function beginSeek(){if($('experiment-seek').disabled||transferBusy||seekDragging)return;seekDragging=true;seekWasRunning=replayActive?player.playing:running;if(replayActive)player.playing=false;else settings({running:false});}
function sendSeek(resume){
  if($('experiment-seek').disabled||transferBusy)return;
  clearTimeout(seekTimer);lastSeekSent=performance.now();const value=+$('experiment-seek').value;
  if(replayActive){player.seek(value);player.playing=resume;renderer.reset();return;}
  pendingSeek=++seekSerial;running=resume;worker.postMessage({type:'seek',time:value,running:resume,request_id:pendingSeek});$('pause').textContent=resume?'停止摆动':'继续摆动';
}
$('experiment-seek').onpointerdown=beginSeek;
$('experiment-seek').oninput=()=>{if($('experiment-seek').disabled||transferBusy)return;beginSeek();clearTimeout(seekTimer);if(performance.now()-lastSeekSent>120)sendSeek(false);else seekTimer=setTimeout(()=>sendSeek(false),120);if(snapshot)updateExperimentTimeline(snapshot);};
$('experiment-seek').onchange=()=>{if($('experiment-seek').disabled||transferBusy)return;const resume=seekWasRunning;seekDragging=false;sendSeek(resume);};
$('goal').onchange=()=>initialize('down');
$('target').oninput=()=>{const v=+$('target').value;$('target-value').textContent=v.toFixed(2)+' m';settings({target:v});};
$('arena').onclick=e=>{if(replayActive||!arenaGeometry)return;const r=$('arena').getBoundingClientRect(),v=clamp((e.clientX-r.left-arenaGeometry.center)/arenaGeometry.scale,-parameters.rail*.6,parameters.rail*.6);$('target').value=v;$('target').oninput();};
$('force').oninput=()=>{$('force-value').textContent=$('force').value+' N';};
$('force').onchange=()=>initialize('custom',snapshot?.state);
$('sensor').onchange=()=>initialize('near');$('observer').onchange=()=>settings({observer:$('observer').value});
$('hide').onchange=()=>{showHidden=$('hide').checked;renderer.trail=[];};$('ghost').onchange=()=>showGhost=$('ghost').checked;
$('noise').oninput=()=>{$('noise-value').textContent=(+$('noise').value).toFixed(3);settings({noise:+$('noise').value});};
$('retry').onchange=()=>settings({autoRetry:$('retry').checked});$('dt').onchange=()=>{settings({stepSize:+$('dt').value});$('integration-label').textContent=(+$('dt').value*1000).toFixed(1)+' ms';setNotice(`物理步长 ${(+$('dt').value*1000).toFixed(1)} ms · RK4；控制周期随步长为 4 个物理步。`);};
$('apply-physics').onclick=()=>{const l=+$('length').value,r=+$('rail').value;if(l<.2||l>1.5||r<1.5||r>6){setNotice('杆长需要在 0.2～1.5 m，轨道半长需要在 1.5～6 m。',true);return;}parameters.length=l;parameters.rail=r;initialize('near');};
function push(sign){if(replayActive){setNotice('轨迹复现中不施加扰动；点击“返回实时实验”继续操作。');return;}worker.postMessage({type:'impulse',tip:sign*12});setNotice(`顶端施加 ${sign*12} N 水平力，持续 0.12 s；已按几何 Jacobian 转为广义力。`);}
$('push-left').onclick=()=>push(-1);$('push-right').onclick=()=>push(1);
$('trail').onclick=()=>{showTrail=!showTrail;renderer.trail=[];$('trail').setAttribute('aria-pressed',String(showTrail));};
$('fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else $('simulation').requestFullscreen().catch(()=>setNotice('当前浏览器未开放全屏，可以放大页面。'));};
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA','BUTTON','A'].includes(e.target.tagName)||document.querySelector('dialog[open]'))return;if(e.code==='Space'){e.preventDefault();$('pause').click();}if(e.code==='ArrowLeft'){e.preventDefault();push(-1);}if(e.code==='ArrowRight'){e.preventDefault();push(1);}if(e.code==='KeyR')initialize('random');});
let editorOrder=3;
function openInitialEditor(order=n){
  editorOrder=order;
  $('initial-fields').innerHTML=`<div class="initial-row initial-head"><span>初始量</span><span>角度 / °</span><span>角速度 / °/s</span></div><div class="initial-row"><span>小车 / m, m/s</span><input aria-label="初始小车位置" id="initial-x" type="number" value="0" min="${-parameters.rail}" max="${parameters.rail}" step="0.1"><input aria-label="初始小车速度" id="initial-v" type="number" value="0" step="0.1"></div>`+Array.from({length:order},(_,i)=>`<div class="initial-row"><span>摆杆 ${i+1}</span><input aria-label="摆杆 ${i+1} 初始角度" id="initial-angle-${i}" type="number" value="180" step="1"><input aria-label="摆杆 ${i+1} 初始角速度" id="initial-omega-${i}" type="number" value="0" step="1"></div>`).join('')+`<label class="range-label" for="initial-goal">希望收敛到</label><select id="initial-goal">${goalChoices(order).map(code=>`<option value="${code}">${targetLabel(code)}</option>`).join('')}</select>`;
  $('initial-goal').value=goalChoices(order).includes(selectedTarget)?selectedTarget:'U'.repeat(order);$('start-custom').textContent='求解并演示 →';$('initial-dialog').showModal();
}
$('edit-initial').onclick=()=>openInitialEditor();
$('start-custom').onclick=()=>{
  const order=editorOrder,x=Array(2*(order+1)).fill(0);x[0]=+$('initial-x').value;x[order+1]=+$('initial-v').value;
  for(let i=0;i<order;i++){x[i+1]=+$(`initial-angle-${i}`).value*rad;x[order+2+i]=+$(`initial-omega-${i}`).value*rad;}
  if(!x.every(Number.isFinite)||Math.abs(x[0])>parameters.rail){setNotice('请输入有效数值，小车初始位置必须在轨道内。',true);return;}
  if(replayActive)exitReplay();n=order;goalOptions(order,$('initial-goal').value);
  $('initial-dialog').close();initialize('custom',x);
};
function download(name,type,text){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function exportData(data){
  const header=['time_s','cart_m',...Array.from({length:n},(_,i)=>`theta${i+1}_rad`),'cart_velocity_m_s',...Array.from({length:n},(_,i)=>`omega${i+1}_rad_s`),'force_N','energy_J'];
  const rows=telemetry.buffer.rows.map(r=>[r.time,...r.state,r.force,r.energy]);
  download(`pendulum-${n}-signals.csv`,'text/csv;charset=utf-8','\uFEFF'+[header.join(','),...rows.map(r=>r.join(','))].join('\r\n'));
  download(`pendulum-${n}-experiment.json`,'application/json',JSON.stringify({version:'2.0.0',parameters:data.parameters,solver:{method:'RK4',dt:data.stepSize},state:data.state,sensor:$('sensor').value,observer:$('observer').value,controller:$('controller').value,noise:+$('noise').value,random_state:data.seed,time:snapshot?.time,design,metrics:snapshot},null,2));
  setNotice('已导出完整状态、角速度、控制力和能量，以及实验快照。');
}
$('export').onclick=()=>replayActive?download(`pendulum-${n}-success-replay.json`,'application/json',JSON.stringify(player.clip)):worker.postMessage({type:'export'});

function sceneLabels(){
  $('orders').querySelectorAll('button').forEach(b=>b.classList.toggle('selected',+b.dataset.order===n));
  $('force').value=parameters.max_force;$('force-value').textContent=parameters.max_force+' N';$('length').value=parameters.length;$('rail').value=parameters.rail;
  $('dimension').textContent=`${2*(n+1)} 维状态`;$('order-title').textContent=(labels[n]||n)+'重倒立摆';$('order-label').textContent=english[n]||`${n}-LINK`;
  $('legend').innerHTML=Array.from({length:n},(_,i)=>`<span><i style="background:${colors[i]}"></i>θ${i+1}</span>`).join('');
  buildAnalysis();renderer.reset();
}
async function captureSuccess(message){
  const clipDesign=replayActive?liveContext.design:design;
  if(!clipDesign||clipDesign.parameters.n!==message.parameters.n)return;
  if(!Object.entries(message.parameters).every(([key,value])=>clipDesign.parameters[key]===value)||message.target_angles.some((a,i)=>Math.abs(wrap(a-clipDesign.target_angles[i]))>1e-9))return;
  const clip={order:message.parameters.n,pattern:message.target_angles.map(a=>Math.cos(a)>0?'U':'D').join(''),parameters:message.parameters,design:clipDesign,target_angles:message.target_angles,frames:message.frames,target:message.target,settled_at:message.settled_at,sample_dt:message.sample_dt,source:'我的最近成功',created_at:new Date().toISOString()};
  try{await saveSuccess(clip);const response=await fetch('/api/repository/record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(clip)});if(!response.ok)throw Error('仓库保存失败');$('replay-hint').textContent=`已保存你的 ${clip.order} 重成功实验 · 已进入初态仓库`;refreshInventoryCount();if(!replayActive)setNotice('已经连续稳定 2 秒，本次成功过程已自动保存到初态仓库。');}
  catch(err){$('replay-hint').textContent='本次运行已成功；浏览器存储不可用，验证示例仍可轨迹复现。';}
}
function showClip(clip){
  clip={...clip,pattern:clip.pattern||(clip.target_angles||clip.design.target_angles||Array(clip.order).fill(0)).map(a=>Math.cos(a)>0?'U':'D').join('')};
  player.load(clip);
  if(!replayActive){liveContext={n,design,parameters:{...parameters},running,speed:$('speed').value,goal:$('goal').value,hint:$('replay-hint').textContent,signalBuffer:telemetry.buffer,signalCutoff:telemetry.cutoff,disabled:[...document.querySelectorAll('.sidebar button,.sidebar select,.sidebar input')].map(el=>[el,el.disabled])};settings({running:false});}
  replayActive=true;n=clip.order;design=clip.design;Object.assign(parameters,clip.parameters);snapshot=player.snapshot();
  telemetry.replay(clip,player.model);
  liveContext.disabled.forEach(([el])=>el.disabled=true);
  player.loop=true;$('exit-replay').classList.remove('hidden');$('loading').classList.add('hidden');document.body.classList.add('replaying');
  $('replay-seek').max=String(player.duration);$('replay-seek').value='0';player.speed=simulationRate($('speed').value);sceneLabels();
  goalOptions(n,clip.pattern||'U'.repeat(n));$('step').textContent='单帧 ›';$('step').title='推进一个记录采样帧';$('simulation').querySelector('.arena-help').textContent='真实成功记录 · 拖动进度查看 · 轨迹复现不施加扰动';$('replay-hint').textContent=clip.title||clip.source;
  setNotice(`${clip.source} · ${n} 重 → ${targetLabel(clip.pattern||'U'.repeat(n))} · 可拖动进度或慢放。`);
}
function exitReplay(){
  if(!replayActive)return;
  replayActive=false;player.playing=false;n=liveContext.n;design=liveContext.design;Object.assign(parameters,liveContext.parameters);snapshot=liveSnapshot;running=liveContext.running;telemetry.buffer=liveContext.signalBuffer;telemetry.cutoff=liveContext.signalCutoff||0;telemetry.setOrder(n);telemetry.ranges={};telemetry.hover=null;telemetry.lastReceive=performance.now();
  liveContext.disabled.forEach(([el,disabled])=>el.disabled=disabled);$('speed').value=liveContext.speed;goalOptions(n,liveContext.goal);$('replay-hint').textContent=liveContext.hint;settings({running});
  $('replay-controls').classList.add('hidden');$('exit-replay').classList.add('hidden');document.body.classList.remove('replaying');$('pause').textContent=running?'停止摆动':'继续摆动';sceneLabels();
  $('step').textContent='单步 ›';$('step').title='停止摆动时推进 1 毫秒';$('simulation').querySelector('.arena-help').innerHTML='点击轨道设置目标 <span>·</span> ← → 施加扰动 <span>·</span> Space 停止摆动';
  if(snapshot?.planning)loading('继续起摆规划','实时对象仍保持原来的物理状态，正在等待求解结果。');else setNotice('已返回实时实验，状态保持在观看轨迹复现之前。');
}
$('exit-replay').onclick=exitReplay;
$('replay-toggle').onclick=()=>player.playing=!player.playing;
$('replay-seek').oninput=()=>{player.seek(+$('replay-seek').value);renderer.reset();};
$('replay-speed').onchange=()=>{player.speed=+$('replay-speed').value;$('speed').value=$('replay-speed').value;};
$('replay-restart').onclick=()=>{player.seek(0);player.playing=true;renderer.reset();};

const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function initialKey(row){return JSON.stringify([row.order,row.initial.map((v,i)=>{let a=i>0&&i<=row.order?wrap(v):v;if(i>0&&i<=row.order&&Math.abs(Math.abs(a)-Math.PI)<5e-7)a=Math.PI;return +a.toFixed(6);})]);}
function previewSVG(card){
  const order=card.order,s=card.initial,pts=[[s[0],0]];let x=s[0],y=0;
  for(let i=0;i<order;i++){const l=(card.parameters?.length||.65)*(order===1?1:1-.22*i/(order-1));x+=l*Math.sin(s[i+1]);y+=l*Math.cos(s[i+1]);pts.push([x,y]);}
  const minX=Math.min(s[0]-.5,...pts.map(p=>p[0])),maxX=Math.max(s[0]+.5,...pts.map(p=>p[0])),minY=Math.min(-.18,...pts.map(p=>p[1])),maxY=Math.max(.18,...pts.map(p=>p[1]));
  const scale=Math.min(155/(maxX-minX),104/(maxY-minY)),px=v=>95+(v-(minX+maxX)/2)*scale,py=v=>66-(v-(minY+maxY)/2)*scale;
  return `<svg viewBox="0 0 190 135" role="img" aria-label="${order} 重摆初始姿态"><path d="M 14 ${py(0)+14} H 176" stroke="#d6e1ef" stroke-width="3"/><rect x="${px(s[0])-13}" y="${py(0)-2}" width="26" height="15" rx="4" fill="#456b9f"/><circle cx="${px(s[0])-7}" cy="${py(0)+14}" r="3" fill="#758eae"/><circle cx="${px(s[0])+7}" cy="${py(0)+14}" r="3" fill="#758eae"/>${pts.slice(0,-1).map((p,i)=>`<path d="M ${px(p[0])} ${py(p[1])} L ${px(pts[i+1][0])} ${py(pts[i+1][1])}" stroke="${colors[i]}" stroke-width="6" stroke-linecap="round"/><circle cx="${px(pts[i+1][0])}" cy="${py(pts[i+1][1])}" r="4" fill="white" stroke="${colors[i]}" stroke-width="2"/>`).join('')}</svg>`;
}
function equilibriumCardCode(card){
  if(!card||Math.abs(card.initial[0])>1e-7||card.initial.slice(card.order+1).some(v=>Math.abs(v)>1e-7)||card.initial.slice(1,card.order+1).some(v=>Math.abs(Math.sin(v))>1e-7))return null;
  return equilibriumCode(card.initial.slice(1,card.order+1));
}
function cardTitle(card,index){
  const code=equilibriumCardCode(card);
  if(code)return code==='D'.repeat(card.order)?'完全下垂 · 静止':poseArrows(code)+' · 静止稳态';
  return card.preset||`自定义初态 ${index+1}`;
}
function warehousePresets(order){
  if(order!==3)return [];
  const toState=(theta,omega,x=0,v=0)=>[x,...theta.map(v=>v*rad),v,...omega.map(v=>v*rad)];
  return [
    ['近下垂 · 带角速度',toState([175,185,170],[8,-6,10])],
    ['折叠姿态 · 静止',toState([90,-60,150],[0,0,0])],
    ['近直立 · 静止',toState([3,-2,1],[0,0,0])],
    ['不对称 · 旋转中',toState([45,-80,130],[20,-10,5])],
    ['轨道偏置 · 下垂',toState([180,180,180],[0,0,0],.35,.1)]
  ].map(([preset,initial])=>({order,initial,preset,parameters:{...parameters,n:order},solutions:[]}));
}
async function refreshInventoryCount(){
  try{const r=await fetch(`/api/repository?order=${n}`);if(!r.ok)return;const data=await r.json();$('inventory-count').textContent=String(new Set(data.solutions.map(initialKey)).size);}
  catch{}
}
async function refreshInventory(){
  const order=+$('inventory-order').value,prior=selectedCard?initialKey(selectedCard):null;
  $('inventory-summary').textContent='读取初值与路径解…';
  try{
    const response=await fetch(`/api/repository?order=${order}`);if(!response.ok)throw Error('仓库暂时无法读取');const data=await response.json();
    const groups=new Map();
    for(const row of data.solutions){const key=initialKey(row);if(!groups.has(key))groups.set(key,{...row,solutions:[]});groups.get(key).solutions.push(row);}
    const saved=groups.size;for(const card of warehousePresets(order)){const key=initialKey(card);if(!groups.has(key))groups.set(key,card);}
    const priority=card=>{const code=equilibriumCardCode(card);return code==='D'.repeat(order)?0:code?1+goalChoices(order).indexOf(code):999;};
    inventoryGroups=[...groups.values()].sort((a,b)=>priority(a)-priority(b));selectedCard=inventoryGroups.find(c=>initialKey(c)===prior)||null;
    $('inventory-total').textContent=`${saved} 个已存初态`;$('inventory-summary').textContent=`已存 ${data.solutions.length} 条路径 · ${Object.values(data.coverage).filter(v=>v>0).length} / ${goalChoices(order).length} 个目标已有解`;
    $('inventory-cards').innerHTML=inventoryGroups.map((card,index)=>`<article class="initial-card ${card===selectedCard?'chosen':''}" role="button" tabindex="0" data-card="${index}" aria-label="选择 ${escapeHTML(cardTitle(card,index))}"><div class="initial-card-top"><span>${card.solutions.length?'已入库':'预设 · 待求解'}</span><b>${new Set(card.solutions.map(s=>s.pattern)).size} / ${goalChoices(order).length} 目标</b></div>${previewSVG(card)}<h3>${escapeHTML(cardTitle(card,index))}</h3><div class="card-state-head"><span>摆杆</span><span>角度 θ</span><span>角速度 ω</span></div>${Array.from({length:order},(_,i)=>`<div class="card-state-row"><span style="color:${colors[i]}">杆 ${i+1}</span><b>${(card.initial[i+1]*deg).toFixed(1)}°</b><b>${(card.initial[order+2+i]*deg).toFixed(1)}°/s</b></div>`).join('')}<div class="card-cart-state">x ${card.initial[0].toFixed(2)} m <span>v ${card.initial[order+1].toFixed(2)} m/s</span></div></article>`).join('')||'<p class="inventory-empty">还没有成功记录。点击“手动输入初值”建立第一次实验。</p>';
    renderTargets();refreshInventoryCount();
  }catch(err){$('inventory-summary').textContent=String(err.message||err);}
}
function renderTargets(){
  $('inventory-dialog').querySelector('.inventory-body').classList.toggle('has-selection',!!selectedCard);
  const order=+$('inventory-order').value,patterns=goalChoices(order);
  if(!patterns.includes(selectedTarget))selectedTarget=patterns[0];
  $('selected-card-title').textContent=selectedCard?cardTitle(selectedCard,inventoryGroups.indexOf(selectedCard)):'先选择一张初态卡片';
  $('selected-card-detail').textContent=selectedCard?`${order} 重摆 · 初值已选定，再选择希望收敛到的姿态。`:'卡片中的 θ 为角度，ω 为角速度。';
  $('inventory-targets').innerHTML=patterns.map((code,i)=>{const saved=selectedCard?.solutions.find(s=>s.pattern===code);return `<button class="target-option ${code===selectedTarget?'selected':''}" data-target="${code}" ${selectedCard?'':'disabled'}><span class="target-arrows">${[...code].map(c=>`<i class="${c==='U'?'up':'down'}">${c==='U'?'↑':'↓'}</i>`).join('')}</span><span>${targetLabel(code)}</span><small>${saved?'已保存 · 可演示':equilibriumCardCode(selectedCard)===code?'当前稳态 · 可保持':'待求解'}</small></button>`;}).join('');
  const found=selectedCard?.solutions.find(s=>s.pattern===selectedTarget);
  const fullyHanging=selectedCard&&Math.abs(selectedCard.initial[0])<1e-10&&selectedCard.initial.slice(order+1).every(v=>Math.abs(v)<1e-10)&&selectedCard.initial.slice(1,order+1).every(v=>Math.abs(wrap(v-Math.PI))<1e-10);
  const waiting=fullyHanging&&!found&&selectedTarget!=='D'.repeat(order);
  $('inventory-play').disabled=!selectedCard||waiting;$('inventory-play').textContent=!selectedCard?'选择初态与目标':found?'▶ 开始演示':equilibriumCardCode(selectedCard)===selectedTarget?'▶ 保持此稳态':waiting?'等待离线预优化':'求解这个组合 →';
  $('inventory-path-detail').textContent=found?`${found.status==='recorded'?'实时成功记录':'已验证路径'} · ${(found.settled_at||found.duration).toFixed(2)} s 进入稳定 · 峰值力 ${found.peak_force.toFixed(1)} N · 轨道行程 ±${found.max_cart.toFixed(2)} m`:waiting?'该完全下垂组合正在离线批量预优化，完成后可以直接演示；这里不会现场启动优化。':'尚未保存这个自定义初值与目标的路径。求解通过真实积分校验后，会自动记录到仓库。';
}
$('open-inventory').onclick=()=>{$('inventory-order').value=String(n);$('inventory-dialog').showModal();refreshInventory();};
$('close-inventory').onclick=()=>$('inventory-dialog').close();$('inventory-refresh').onclick=refreshInventory;$('inventory-order').onchange=()=>{selectedCard=null;refreshInventory();};
$('inventory-back').onclick=()=>{selectedCard=null;renderTargets();};
$('inventory-new').onclick=()=>{const order=+$('inventory-order').value;$('inventory-dialog').close();openInitialEditor(order);};
$('inventory-cards').onclick=e=>{const card=e.target.closest('[data-card]');if(!card)return;selectedCard=inventoryGroups[+card.dataset.card];if(selectedCard.solutions.length)selectedTarget=selectedCard.solutions[0].pattern;document.querySelectorAll('.initial-card').forEach(el=>el.classList.toggle('chosen',el===card));renderTargets();};
$('inventory-cards').onkeydown=e=>{if(e.code==='Enter'||e.code==='Space'){e.preventDefault();e.target.closest('[data-card]')?.click();}};
$('inventory-targets').onclick=e=>{const option=e.target.closest('[data-target]');if(option){selectedTarget=option.dataset.target;renderTargets();}};
$('inventory-play').onclick=async()=>{
  if(!selectedCard)return;const found=selectedCard.solutions.find(s=>s.pattern===selectedTarget);$('inventory-play').disabled=true;
  try{
    if(found?.plugin){if(replayActive)exitReplay();n=selectedCard.order;Object.assign(parameters,selectedCard.parameters);goalOptions(n,selectedTarget);$('inventory-dialog').close();await initialize('custom',[...selectedCard.initial]);await playTransfer(equilibriumCardCode(selectedCard),selectedTarget);}
    else if(found){const response=await fetch(`/api/repository/${found.id}`);if(!response.ok)throw Error('这条轨迹复现未能加载');const clip=await response.json();showClip(clip);$('inventory-dialog').close();}
    else{if(replayActive)exitReplay();n=selectedCard.order;Object.assign(parameters,selectedCard.parameters);$('force').value=parameters.max_force;$('force-value').textContent=parameters.max_force+' N';goalOptions(n,selectedTarget);$('inventory-dialog').close();initialize('custom',[...selectedCard.initial]);}
  }catch(err){$('inventory-path-detail').textContent=String(err.message||err);}
  finally{$('inventory-play').disabled=false;}
};
function updateBankStatus(){
  const ready=bankRows.filter(r=>r.status==='ready').length,row=bankRows.find(r=>r.pattern===$('goal').value),base=n<=20&&$('goal').value==='D'.repeat(n);
  const labels={ready:'离线方案就绪',queued:'排队预计算',computing:'正在离线计算',retry_pending:'等待下一轮搜索'};
  const compatible=row?.parameters&&Object.entries(parameters).every(([k,v])=>row.parameters[k]===v);
  $('precomputed-status').textContent=`${n} 重：${ready} / ${2**n-1} 个默认方案就绪 · 当前目标${base?'为基态，可直接保持或由其他稳态转入':row?.status==='ready'&&!compatible?'参数已修改，需重新离线预优化':labels[row?.status]||'尚未预计算'}`;
  for(const option of $('goal').options){const item=bankRows.find(r=>r.pattern===option.value);option.textContent=targetLabel(option.value)+(n<=20&&option.value==='D'.repeat(n)?'  · 基态':item?.status==='ready'?'  ✓ 预优化就绪':item?.status==='computing'?'  · 计算中':'  · 待预优化');}
  $('down').title=base?'保持完全下垂基态':row?.status==='ready'?'直接加载离线预优化方案，立即起摆':'该目标暂未通过离线验收，不会现场启动优化';

}
async function refreshBank(){
  try{const response=await fetch('/api/precomputed');if(!response.ok)return;bankTotal=await response.json();bankRows=bankTotal.entries.filter(r=>r.order===n);updateBankStatus();}catch{}
}
$('open-settings').onclick=()=>$('settings-dialog').showModal();
$('restore-defaults').onclick=()=>{
  Object.assign(parameters,{n,cart_mass:1.5,length:.65,mass:.3,gravity:9.81,damping:.006,cart_damping:.08,max_force:120,rail:2.4,point_mass:false});
  $('force').value=120;$('force-value').textContent='120 N';$('length').value=.65;$('rail').value=2.4;$('dt').value='0.001';$('integration-label').textContent='1 ms';
  $('controller').value='auto';$('sensor').value='full_state';$('noise').value=0;$('noise-value').textContent='0.000';$('settings-dialog').close();initialize('down');
};
$('open-routes').onclick=()=>{renderTransferMatrix();$('routes-dialog').showModal();};
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());

function fillTransferOptions(source=activePreset==='down'?'D'.repeat(n):equilibriumCode(design?.target_angles||Array(n).fill(0)),destination=null){
  const choices=equilibriaFor(n),base='D'.repeat(n);
  for(const side of ['from','to'])$('transfer-'+side+'-options').innerHTML=choices.map(code=>`<button type="button" class="pose-option" data-pose="${code}" aria-label="${poseArrows(code)}${code===base?'（基态）':''}" aria-pressed="false"><span class="pose-arrows" aria-hidden="true">${[...code].map((c,i)=>`<i style="--rod-color:${colors[i]}">${c==='U'?'↑':'↓'}</i>`).join('')}</span><span class="pose-dot" aria-hidden="true"></span></button>`).join('');
  $('transfer-from').value=choices.includes(source)?source:choices[0];
  $('transfer-to').value=choices.includes(destination)?destination:source===base?choices[0]:base;
  $('pose-order').textContent=n;syncTransferPickers();
  transferOrder=n;renderTransferMatrix();
}
function syncTransferPickers(){
  const source=$('transfer-from').value,target=$('transfer-to').value;
  for(const side of ['from','to']){
    const value=side==='from'?source:target;
    $('transfer-'+side+'-preview').textContent=poseArrows(value);
    for(const button of $('transfer-'+side+'-options').children){
      const code=button.dataset.pose,ready=side==='from'?transferBank?.entries.some(r=>r.order===n&&r.source===code&&transferCompatible(r)):transferCompatible(transferRow(source,code));
      const selected=code===value;
      button.disabled=side==='to'&&code===source;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));
      button.classList.toggle('available',!!ready);button.classList.toggle('same-pose',side==='to'&&code===source);
      button.title=poseArrows(code)+(code==='D'.repeat(n)?' · 完全下垂基态':'')+(side==='to'?(code===source?' · 与起点相同':ready?' · 路径已验收，可演示':' · 路径求解中'):' · 选为起点');
    }
  }
}
function transferRow(source,target){return transferBank?.entries.find(row=>row.order===n&&row.source===source&&row.target===target);}
function transferCompatible(row){return row?.status==='ready'&&Object.entries(parameters).every(([key,value])=>row.parameters?.[key]===value);}
function transferResting(s){return !!s&&!s.planning&&!s.plan_active&&s.running&&s.stable>=1&&Math.abs(s.state[0])<.04&&Math.max(...s.state.slice(n+1).map(Math.abs))<.04;}
function renderTransferMatrix(){
  if(n>20)return;
  syncTransferPickers();
  const choices=equilibriaFor(n),a=$('transfer-from').value,b=$('transfer-to').value;
  $('transfer-matrix').classList.toggle('fourth-order-matrix',n>=4);
  $('transfer-matrix').innerHTML=`<table><thead><tr><th>起点 ↓ / 目标 →</th>${choices.map(code=>`<th title="${targetLabel(code)}">${poseArrows(code)}</th>`).join('')}</tr></thead><tbody>${choices.map(source=>`<tr><th title="${targetLabel(source)}">${poseArrows(source)}</th>${choices.map(target=>{const row=transferRow(source,target),ready=transferCompatible(row);return `<td><button data-transfer-source="${source}" data-transfer-target="${target}" class="${source===a&&target===b?'selected ':''}${ready?'ready':''}" aria-label="${targetLabel(source)} 转 ${targetLabel(target)}" ${source===target||!ready?'disabled':''} title="${source===target?'同一姿态，无需转场':ready?row.duration.toFixed(2)+' s · 峰值 '+row.verification.max_force.toFixed(1)+' N'+(row.route_waypoints?' · 连续衔接：'+row.route_waypoints.map(poseArrows).join(' → '):' · 直达'):'离线预计算中'}">${source===target?'—':ready?'▶':row?.status==='computing'?'◌':'·'}</button></td>`;}).join('')}</tr>`).join('')}</tbody></table>`;
}
async function startTransfer(destination){
  if(n>20||!design||!snapshot||transferBusy)return;
  const source=equilibriumCode(design.target_angles);if(source===destination)return;
  if(!transferResting(snapshot))return;
  const row=transferRow(source,destination);
  if(!transferCompatible(row)){cruise=null;goalOptions(n,source);setNotice('当前参数的这条稳态互转尚未通过离线验收。',true);return;}
  const gen=generation,token=++transferToken;transferBusy=true;transferSummary='';transferRunIntent=true;
  try{
    const response=await fetch('/api/transition',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parameters,source,target:destination,state:snapshot.state})});
    if(!response.ok)throw Error((await response.json()).detail||'无法加载转场');
    const result=await response.json();if(gen!==generation||token!==transferToken)return;
    pendingTransfer={...result,target:destination,source,request_id:token};
    worker.postMessage({type:'transition',design:result.design,plan:result.plan,request_id:token,loop:!cruise});
  }catch(error){if(gen===generation&&token===transferToken){transferBusy=false;pendingTransfer=null;cruise=null;goalOptions(n,source);setNotice(String(error.message||error),true);}}
}
async function playTransfer(source,destination,{tour=false}={}){
  if(n>20||source===destination)return;
  const row=transferRow(source,destination);
  if(!transferCompatible(row)){setNotice('这条路径尚未完成离线验收，请选择有绿色标记的终点，或等待远端计算完成。',true);return;}
  if(replayActive){const order=n,p={...parameters};exitReplay();n=order;Object.assign(parameters,p);fillTransferOptions(source,destination);}
  cancelPlanning();if(!tour)cruise=null;activeTransfer=null;pendingTransfer=null;
  pendingSeek=null;seekDragging=false;clearTimeout(seekTimer);settings({running:false});
  const gen=++generation,token=++transferToken;transferBusy=true;transferSummary='';transferRunIntent=true;running=true;$('pause').textContent='停止摆动';
  $('experiment-seek').disabled=true;
  $('transfer-from').value=source;$('transfer-to').value=destination;renderTransferMatrix();
  setNotice(`正在载入 ${poseArrows(source)} → ${poseArrows(destination)}，随后跳到起点演示。`);
  try{
    const response=await fetch('/api/transition',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parameters,source,target:destination,jump_to_start:true})});
    if(!response.ok)throw Error((await response.json()).detail||'路径加载失败');
    const result=await response.json();if(gen!==generation||token!==transferToken)return;
    pendingTransfer={...result,target:destination,source,request_id:token};worker.postMessage({type:'play-transition',design:result.design,plan:result.plan,request_id:token,loop:!tour});
  }catch(error){if(gen===generation&&token===transferToken){transferBusy=false;pendingTransfer=null;cruise=null;setNotice(error.message,true);}}
}
function updateTransferUI(s){
  $('transfer-panel').classList.toggle('hidden',n>20);$('swingup-panel').classList.toggle('hidden',n<=20);
  if(n>20){$('transfer-note').textContent='';return;}
  if(transferOrder!==n)fillTransferOptions();
  const rows=transferBank?.entries.filter(row=>row.order===n)||[],ready=rows.filter(transferCompatible).length,total=2**n*(2**n-1);
  $('transfer-count').textContent=`${ready}/${total}`;$('transfer-total').textContent=transferBank?`${ready} / ${total} 已就绪`:'';
  if(!replayActive&&activeTransfer&&s.planning){activeTransfer=null;cruise=null;}
  if(!replayActive&&activeTransfer&&cruise&&!s.plan_active&&!s.planning&&s.stable>=STABLE_HOLD_SECONDS&&Math.abs(s.state[n+1])<.03){
    activeTransfer=null;if(cruise)cruise.completed++;renderTransferMatrix();
  }
  if(!replayActive&&!activeTransfer&&!transferBusy&&cruise&&transferResting(s)){
    if(cruise.completed>=cruise.total){cruise.completed=0;cruise.round=(cruise.round||1)+1;setNotice(`序列演示开始第 ${cruise.round} 轮。`);}
    else{$('transfer-from').value=equilibriumCode(design.target_angles);$('transfer-to').value=cruise.path[cruise.completed+1];syncTransferPickers();startTransfer(cruise.path[cruise.completed+1]);}
  }
  const source=$('transfer-from').value,destination=$('transfer-to').value;
  const cruiseReady=n<4||transferBank?.cruise_ready?.[n]===true;
  $('transfer-cruise').textContent=cruise?`结束序列 ${cruise.completed}/${cruise.total}`:'↻ 序列演示';$('transfer-cruise').disabled=ready<total||!cruiseReady;
  $('transfer-cruise').title=cruiseReady?'依次演示全部有向路径':'全部路径通过连续串联验收后开放序列演示';
  const remote=transferBank?.remote_computes?.[n]??transferBank?.remote_compute,remoteRunning=remote?.jobs?.some(job=>job.state==='R'),remoteQueued=remote?.jobs?.some(job=>job.state==='Q');
  const computeMessages={auditing_upgrade:'新直达解后台验收中，当前方案照常可玩',auditing_tour:'正在验收全部路径连续序列演示',complete:'全部计算与串联验收完成',refining_direct:'全部可演示，继续优化更短直达路径',complete_with_routes:'全部转场与连续序列演示已通过验收',retry_sync:'等待远程连接恢复后同步',resubmitted:'剩余路径已自动提交续算',needs_search:'剩余路径需要进一步搜索',tour_needs_review:'单条路径已验收，连续序列演示待复验'};
  const computePhase=computeMessages[remote?.phase]||(remoteRunning?'远程并行求解中':remoteQueued?'远程作业排队中':remote?'等待下一批结果同步':'正在准备远程批量计算');
  const routed=rows.filter(r=>transferCompatible(r)&&r.route_waypoints).length;
  const computeNote=n>=4?`${labels[n]}阶 ${ready}/${total} 已通过本机验收${routed?'（'+(ready-routed)+' 条直达 · '+routed+' 条经中间姿态连续衔接）':''} · ${computePhase}`:'';
  $('route-progress').textContent=computeNote;
  $('transfer-note').textContent=replayActive?'正在轨迹复现历史路径；上方仍可直接切换新路径，点击后自动退出轨迹复现并跳到新起点。':activeTransfer?`${activeTransfer.waypoints?activeTransfer.waypoints.map(poseArrows).join(' → ')+' · 连续衔接':poseArrows(activeTransfer.source)+' → '+poseArrows(activeTransfer.target)} · ${s.stable>=.5?'稳态保持 · '+Math.max(0,STABLE_HOLD_SECONDS-s.stable).toFixed(1)+' s 后'+(cruise?'进入下一组合':'重新起摆'):s.plan_active?'运动进度 '+Math.min(100,(s.time-activeTransfer.start_time)/activeTransfer.duration*100).toFixed(0)+'%':'落稳中'} · 可随时切换其他路径`:
    transferBusy?'载入后自动跳到起点，无需等待当前姿态停稳。':transferSummary||computeNote||'切换起点或终点即开始运动；稳定保持 10 秒后自动重新起摆。';
}
async function refreshTransfers(){
  try{const response=await fetch('/api/transitions');if(!response.ok)return;transferBank=await response.json();if(n<=20)renderTransferMatrix();}catch{}
}
for(const side of ['from','to'])$('transfer-'+side+'-options').onclick=e=>{
  const button=e.target.closest('[data-pose]');if(!button)return;
  if(button.disabled||$('transfer-'+side).value===button.dataset.pose)return;
  const previous=$('transfer-from').value;
  $('transfer-'+side).value=button.dataset.pose;cruise=null;transferSummary='';renderTransferMatrix();
  if($('transfer-from').value===$('transfer-to').value)$('transfer-to').value=previous!==button.dataset.pose?previous:equilibriaFor(n).find(code=>code!==button.dataset.pose);
  renderTransferMatrix();playTransfer($('transfer-from').value,$('transfer-to').value);
  if(snapshot)updateTransferUI(snapshot);
};
$('transfer-cruise').onclick=()=>{
  if(cruise){cruise=null;settings({loop:true});setNotice('已结束序列演示，当前组合稳定保持 10 秒后重新起摆。');return;}
  if(n>20||!design)return;const source=$('transfer-from').value,path=eulerTour(n,source);
  cruise={path,total:path.length-1,completed:0};transferSummary='';playTransfer(source,path[1],{tour:true});
};
$('transfer-matrix').onclick=e=>{
  const button=e.target.closest('[data-transfer-source]');if(!button||button.disabled)return;
  const {transferSource:source,transferTarget:target}=button.dataset;
  $('routes-dialog').close();playTransfer(source,target);
};
setInterval(refreshTransfers,15000);
setInterval(refreshBank,15000);
addEventListener('pagehide',()=>{if(activeJob)fetch(`/api/plan/${activeJob}`,{method:'DELETE',keepalive:true}).catch(()=>{});});
async function discoverOrders(preferred=n){
  const response=await fetch('/api/health');if(!response.ok)throw Error('本机服务尚未就绪');
  const health=await response.json(),orders=health.orders;
  if(!orders?.length)throw Error('motions 目录没有有效的双向轨迹插件');
  $('orders').innerHTML=orders.map(order=>`<button data-order="${order}" class="${order===preferred?'selected':''}">${order}</button>`).join('');
  $('inventory-order').innerHTML=orders.map(order=>`<option value="${order}">${labels[order]||order}重摆 · ${2**order} 种姿态</option>`).join('');
  if(!orders.includes(n))n=orders.includes(3)?3:orders[0];
  $('inventory-order').value=String(n);
}
const updateMotions=$('check-motion-updates');
if(updateMotions)updateMotions.onclick=async()=>{
  updateMotions.disabled=true;updateMotions.textContent='检查中…';
  try{
    const response=await fetch('/api/motions/check',{method:'POST'});if(!response.ok)throw Error(await response.text());
    const report=await response.json();await discoverOrders(n);await refreshTransfers();await refreshBank();await refreshInventoryCount();
    updateMotions.title=`已检查 · ${report.directions??'当前'} 条已验收方向${report.errors?.length?' · '+report.errors.length+' 个文件无效':''}`;
    setNotice(report.errors?.length?`检查完成，${report.errors.length} 个文件无效，保留其原可用版本。`:`轨迹检查完成 · ${report.directions??'当前'} 条已验收方向${report.changed?'，新条目已激活':'，没有新增变化'}。`,!!report.errors?.length);
  }catch(error){setNotice('轨迹检查失败：'+error.message,true);}
  finally{updateMotions.disabled=false;updateMotions.textContent='检查轨迹更新';}
};
(async()=>{try{await discoverOrders();await refreshTransfers();refreshInventoryCount();refreshBank();await initialize();}catch(error){loading('无法打开实验室',error.message);}})();
