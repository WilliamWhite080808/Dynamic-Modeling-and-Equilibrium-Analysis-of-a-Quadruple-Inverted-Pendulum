import fs from 'node:fs';
import assert from 'node:assert/strict';
import {wrap} from '../web/physics.js';
import {equilibriaFor} from '../web/targets.js';
import {eulerTour} from '../web/transfers.js';

const fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let clock=0,timer,last,started,rejected,requests=0;
Object.defineProperty(globalThis,'performance',{value:{now:()=>clock},configurable:true});
globalThis.setInterval=callback=>{timer=callback;};globalThis.onmessage=null;
globalThis.postMessage=m=>{if(m.type==='state')last=m;if(m.type==='transition-started')started=m;if(m.type==='transition-rejected')rejected=m;if(m.type==='plan-request')requests++;};
await import('../web/sim-worker.js');
const send=data=>globalThis.onmessage({data});
function advance(seconds){let maxCart=0;for(let i=0;i<Math.ceil(seconds*250);i++){clock+=4;timer();maxCart=Math.max(maxCart,Math.abs(last.state[0]));}return maxCart;}
const orders=[...new Set(fixtures.map(f=>f.design.parameters.n))];
const designs=new Map(fixtures.flatMap(f=>[[`${f.plan.transition.order}-${f.plan.transition.target}`,f.design],...(f.source_design?[[`${f.plan.transition.order}-${f.plan.transition.source}`,f.source_design]]:[])]));
const cases=new Map(fixtures.map(f=>{const t=f.plan.transition;return [`${t.order}-${t.source}-${t.target}`,f];}));
function begin(n,source){
  const initial=Array(2*(n+1)).fill(0);for(let i=0;i<n;i++)initial[i+1]=source[i]==='U'?0:Math.PI;
  send({type:'init',design:designs.get(`${n}-${source}`),initial,mode:'auto',sensor:'full_state',requirePrecomputed:true});
  assert.ok(last.running,'Base and excited states must all be holdable without a swingup plan');advance(2.5);
}
function transfer(f,chain=false){
  send({type:'settings'}); // Flush the current snapshot without advancing physics.
  const before=structuredClone(last),n=f.design.parameters.n,d=n+1;
  started=null;rejected=null;send({type:'transition',design:f.design,plan:f.plan});
  assert.ok(started&&!rejected,`Hot transfer rejected ${JSON.stringify(f.plan.transition)} ${JSON.stringify(rejected)}`);
  assert.deepEqual(last.state,before.state,'Installing a target must preserve every angle, position and velocity exactly');
  assert.equal(last.time,before.time,'No clock reset');assert.equal(last.epoch,before.epoch,'No renderer epoch reset');
  assert.equal(last.force,before.force,'No instantaneous force change');
  let maxCart=0;
  if(chain){
    // Match the page's earliest automatic hand-off, rather than giving every
    // edge an extra 15 seconds to erase residual motion before the next edge.
    const deadline=last.time+f.plan.duration+15;
    do{maxCart=Math.max(maxCart,advance(.008));}
    while(last.time<deadline&&(last.plan_active||last.stable<2.4||Math.abs(last.state[0])>=.04||Math.max(...last.state.slice(d).map(Math.abs))>=.03));
  }else maxCart=advance(f.plan.duration+15);
  const angle=Math.max(...last.state.slice(1,d).map((a,i)=>Math.abs(wrap(a-f.design.target_angles[i]))));
  const velocity=Math.max(...last.state.slice(d).map(Math.abs));
  assert.ok(angle<.5*Math.PI/180&&last.stable>=2.4&&velocity<.03,`Did not settle: ${JSON.stringify({transition:f.plan.transition,chain,angle,velocity,stage:last.stage,reason:last.reason})}`);
  assert.equal(last.boundaries,0);assert.ok(maxCart<f.design.parameters.rail*.96);
  assert.ok(last.maxForce<=f.design.parameters.max_force+1e-8);
  assert.ok(last.maxForceRate<=500+1e-6,'Force slew bound exceeded');
  assert.equal(requests,0,'Direct transfers must not fall back to a live planner');
  return {...f.plan.transition,chain,clock:last.time,angle_deg:angle*180/Math.PI,max_cart:maxCart,max_force:last.maxForce,max_force_rate:last.maxForceRate};
}
const report={individual:[],continuous:[],rail_contacts:0,live_planner_requests:0};
// Point-play must work from an unrelated moving state, including while paused
// or while another certified transfer is still running.
for(const n of orders){
  const f=fixtures.find(f=>f.design.parameters.n===n),initial=Array(2*(n+1)).fill(.4);initial[0]=.3;
  send({type:'init',design:f.design,initial,mode:'off',sensor:'full_state'});advance(.2);
  if(n===1)send({type:'settings',running:false});
  if(n===3)send({type:'play-transition',design:f.design,plan:f.plan});
  const epoch=last.epoch;started=null;
  send({type:'play-transition',design:f.design,plan:f.plan,request_id:`jump-${n}`});
  assert.ok(started.jumped);assert.equal(started.request_id,`jump-${n}`);assert.equal(last.time,0);assert.deepEqual(last.state,f.plan.initial);
  assert.ok(last.running&&last.plan_active);assert.ok(last.epoch>epoch);
  advance(f.plan.duration+15);
  assert.ok(last.stable>2&&last.boundaries===0);
}
for(const f of fixtures){begin(f.plan.transition.order,f.plan.transition.source);report.individual.push(transfer(f));}
for(const n of orders){
  if(fixtures.filter(f=>f.design.parameters.n===n).length!==2**n*(2**n-1))continue;
  const poses=equilibriaFor(n),path=eulerTour(n,'D'.repeat(n)),edges=path.slice(1).map((b,i)=>`${path[i]}-${b}`);
  assert.equal(path.length,poses.length*(poses.length-1)+1);assert.equal(path[0],path.at(-1));assert.equal(new Set(edges).size,edges.length);
  for(const a of poses)for(const b of poses)if(a!==b)assert.ok(edges.includes(`${a}-${b}`));
  begin(n,path[0]);const records=[];
  for(let i=1;i<path.length;i++)records.push(transfer(cases.get(`${n}-${path[i-1]}-${path[i]}`),true));
  report.continuous.push({order:n,edges:records.length,final_time:last.time,records});
}
// Reject changing the physical plant through the controller-switch message.
const f=fixtures[0];begin(f.plan.transition.order,f.plan.transition.source);const before=structuredClone(last);
send({type:'transition',design:{...f.design,parameters:{...f.design.parameters,mass:.8}},plan:f.plan});
assert.ok(rejected);assert.deepEqual(last.state,before.state);
if(process.argv[3])fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2));
console.log(`PASS: ${report.individual.length} individual hot transfers and ${report.continuous.reduce((sum,r)=>sum+r.edges,0)} chained Euler transfers; exact state/time continuity; passive physics, bounded force/rate, zero rail contacts and planner requests.`);
