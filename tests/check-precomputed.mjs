import fs from 'node:fs';
import assert from 'node:assert/strict';
import {patternsFor} from '../web/targets.js';
import {wrap} from '../web/physics.js';
for(let n=1;n<=5;n++){
  const patterns=patternsFor(n);assert.equal(patterns.length,2**n-1);assert.equal(new Set(patterns).size,patterns.length);
  assert.ok(patterns.every(p=>p.length===n&&p.includes('U')));
}
let clock=0,timer,last,requests=0;
Object.defineProperty(globalThis,'performance',{value:{now:()=>clock},configurable:true});
globalThis.setInterval=callback=>{timer=callback;};globalThis.onmessage=null;
globalThis.postMessage=message=>{if(message.type==='state')last=message;if(message.type==='plan-request')requests++;};
await import('../web/sim-worker.js');
const fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
for(const {design,plan} of fixtures){
  const n=design.parameters.n,d=n+1;
  globalThis.onmessage({data:{type:'init',design,initial:plan.initial,mode:'auto',sensor:'full_state',precomputedPlan:plan,requirePrecomputed:true}});
  assert.equal(last.stage,'swing');assert.equal(last.time,0);assert.equal(last.planning,false);
  assert.ok(last.state.slice(1,d).every(a=>Math.abs(wrap(a-Math.PI))<1e-10),'Must start genuinely hanging');
  for(let i=0;i<(plan.duration+10)*250+2;i++){clock+=4;timer();}
  const angle=Math.max(...last.state.slice(1,d).map((v,i)=>Math.abs(wrap(v-design.target_angles[i]))));
  assert.ok(angle<.5*Math.PI/180&&last.stable>1,`${n} ${plan.pattern} failed immediate-start integration`);
  assert.equal(last.boundaries,0,`${n} ${plan.pattern} relied on hitting a rail stop`);
  assert.ok(last.maxForce<=design.parameters.max_force+1e-8,`${n} ${plan.pattern} exceeded the cart actuator bound`);
  assert.equal(requests,0,'A precomputed hanging run must never ask the live planner');
}
const f=fixtures[0];
globalThis.onmessage({data:{type:'init',design:f.design,initial:f.plan.initial,mode:'auto',requirePrecomputed:true}});
globalThis.onmessage({data:{type:'step'}});
for(let i=0;i<300;i++){clock+=4;timer();}
assert.equal(last.stage,'unprepared');assert.equal(last.time,0);assert.equal(requests,0);
console.log('All target counts and precomputed worker starts PASS; no live optimization requests.');
