import fs from 'node:fs';
import assert from 'node:assert/strict';
import {wrap} from '../web/physics.js';
import {dissipativeForce} from '../web/recovery-policy.js';
const fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
for(const test of fixtures.forces)assert.ok(Math.abs(dissipativeForce(test.state,test.time,test.parameters,test.policy)-test.force)<1e-11);
let clock=0,timer,last,request,captured,requests=0;
Object.defineProperty(globalThis,'performance',{value:{now:()=>clock},configurable:true});
globalThis.setInterval=callback=>{timer=callback;};globalThis.onmessage=null;
globalThis.postMessage=message=>{if(message.type==='state')last=message;if(message.type==='success-captured')captured=message;if(message.type==='plan-request'){request=message;requests++;}};
await import('../web/sim-worker.js');
for(const {design,plan,name=''} of fixtures.plans){
  const initial=[...plan.initial],n=design.parameters.n,d=n+1;
  globalThis.onmessage({data:{type:'init',design,initial,mode:'auto',sensor:'full_state'}});
  globalThis.onmessage({data:{type:'plan-now'}});
  assert.equal(last.time,0);assert.deepEqual(last.state,initial);
  const before=requests;
  globalThis.onmessage({data:{type:'plan-result',epoch:request.epoch,plan}});
  assert.deepEqual(last.state,initial,'Installing a recovery controller must not change any physical state');
  for(let i=0;i<(plan.duration+20)*250+2;i++){clock+=4;timer();}
  const angle=Math.max(...last.state.slice(1,d).map((v,i)=>Math.abs(wrap(v-design.target_angles[i]))));
  assert.ok(angle<.5*Math.PI/180&&last.stable>1,`${n} ${name} recovery failed: ${JSON.stringify({time:last.time,stage:last.stage,angle,stable:last.stable,reason:last.reason,requests,boundaries:last.boundaries})}`);
  assert.equal(last.boundaries,0,`${n} recovery hit a rail stop`);
  assert.ok(last.maxForce<=design.parameters.max_force+1e-8);
  assert.equal(requests,before,`${n} recovery unexpectedly requested another plan`);
  assert.equal(captured.frames[0][0],0,'Long recovery must preserve the original initial frame');
  assert.deepEqual(captured.frames[0].slice(1,-1),initial);
}
console.log('Arbitrary-state recovery: real Worker physics, no state reset, bounded cart force, no rail contact PASS.');
