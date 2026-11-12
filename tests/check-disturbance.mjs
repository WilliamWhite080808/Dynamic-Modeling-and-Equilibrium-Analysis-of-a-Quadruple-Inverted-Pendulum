import fs from 'node:fs';
import assert from 'node:assert/strict';
const design=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let clock=0,timer,last,request;
Object.defineProperty(globalThis,'performance',{value:{now:()=>clock},configurable:true});
globalThis.setInterval=callback=>{timer=callback;};globalThis.onmessage=null;
globalThis.postMessage=message=>{if(message.type==='state')last=message;if(message.type==='plan-request')request=message;};
await import('../web/sim-worker.js');
const d=design.parameters.n+1,up=Array(2*d).fill(0),down=[...up];down.fill(Math.PI,1,d);
globalThis.onmessage({data:{type:'init',design,initial:up,mode:'auto',sensor:'full_state'}});
globalThis.onmessage({data:{type:'impulse',tip:36}});
for(let i=0;i<80&&!request;i++){clock+=4;timer();}
assert.ok(request,'Strong physical disturbance should trigger autonomous recovery');
assert.ok(request.time>=.12-1e-9,'Do not freeze and certify the state before the external pulse has finished');
globalThis.onmessage({data:{type:'init',design,initial:down,mode:'off',sensor:'full_state'}});
for(let i=0;i<200;i++){clock+=4;timer();}
globalThis.onmessage({data:{type:'impulse',tip:36}});
globalThis.onmessage({data:{type:'init',design,initial:down,mode:'off',sensor:'full_state'}});
for(let i=0;i<25;i++){clock+=4;timer();}
for(let i=0;i<down.length;i++)assert.ok(Math.abs(last.state[i]-down[i])<1e-9,'New experiments must not inherit an old external force');
console.log('Pulse timing and complete experiment reset PASS.');
