// Stream accepted plans through the unchanged page Worker; no renderer or
// reference angle is assigned after initialization, including edge hand-offs.
import fs from 'node:fs';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {wrap} from '../web/physics.js';
import {eulerTour} from '../web/transfers.js';

const manifestBytes=fs.readFileSync(process.argv[2]);
const manifest=JSON.parse(manifestBytes),designs=manifest.designs;
const startupOnly=process.argv.includes('--startup-only');
const cases=new Map(manifest.entries.map(r=>[`${r.order}-${r.source}-${r.target}`,r]));
let clock=0,timer,last,started,rejected,requests=0;
Object.defineProperty(globalThis,'performance',{value:{now:()=>clock},configurable:true});
globalThis.setInterval=callback=>{timer=callback;};globalThis.onmessage=null;
globalThis.postMessage=m=>{if(m.type==='state')last=m;if(m.type==='transition-started')started=m;if(m.type==='transition-rejected')rejected=m;if(m.type==='plan-request')requests++;};
await import('../web/sim-worker.js');
const send=data=>globalThis.onmessage({data});
function advance(seconds){let maxCart=0;for(let i=0;i<Math.ceil(seconds*250);i++){clock+=4;timer();maxCart=Math.max(maxCart,Math.abs(last.state[0]));}return maxCart;}
function load(row){
  const bytes=fs.readFileSync(row.file);assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),row.file_sha256);
  const plan=JSON.parse(zlib.gunzipSync(bytes));assert.deepEqual(plan.transition,{order:row.order,source:row.source,target:row.target});
  return plan;
}
const report={passed:false,individual_directions:manifest.entries.length,continuous:[],rail_contacts:0,live_planner_requests:0,
  manifest_sha256:crypto.createHash('sha256').update(manifestBytes).digest('hex'),bank_sha256:manifest.bank_sha256,signatures:manifest.signatures,stable_hold_seconds:5};
for(const n of manifest.orders){
  const path=eulerTour(n,'D'.repeat(n));assert.equal(path.length,2**n*(2**n-1)+1);assert.equal(path[0],path.at(-1));
  const initial=Array(2*(n+1)).fill(0);for(let j=0;j<n;j++)initial[j+1]=Math.PI;
  send({type:'init',design:designs[`${n}-${path[0]}`],initial,mode:'auto',sensor:'full_state',requirePrecomputed:true});advance(2.5);
  const records=[];
  for(let i=1;i<path.length&&(!startupOnly||i<=3);i++){
    const row=cases.get(`${n}-${path[i-1]}-${path[i]}`);assert.ok(row);const plan=load(row);plan.lossy=true;send({type:'settings'});
    const before=structuredClone(last);started=null;rejected=null;send({type:startupOnly&&i===1?'play-transition':'transition',design:designs[`${n}-${row.target}`],plan,sequence:true});
    assert.ok(started&&!rejected,JSON.stringify(rejected));
    if(startupOnly&&i===1){assert.deepEqual(last.state,plan.initial);assert.equal(last.time,0);if(n===5)assert.equal(last.transition.strict_capture,true);}
    else{assert.deepEqual(last.state,before.state);assert.equal(last.time,before.time);assert.equal(last.epoch,before.epoch);assert.equal(last.force,before.force);}
    let maxCart=0,ticks=0;const deadline=last.time+plan.duration+60,maxTicks=Math.ceil((plan.duration+60)/.008)+2;
    do{
      maxCart=Math.max(maxCart,advance(.008));ticks++;
      assert.ok(last.running&&requests===0&&last.boundaries===0,`Stopped edge ${n}:${row.source}->${row.target} ${JSON.stringify(last)} requests=${requests}`);
    }while(ticks<maxTicks&&last.time<deadline&&(last.plan_active||last.stable<5||Math.abs(last.state[0])>=.03||Math.max(...last.state.slice(n+1).map(Math.abs))>=.03));
    const angle=Math.max(...last.state.slice(1,n+1).map((a,j)=>Math.abs(wrap(a-designs[`${n}-${row.target}`].target_angles[j]))));
    assert.ok(angle<.5*Math.PI/180&&last.stable>=5&&Math.max(...last.state.slice(n+1).map(Math.abs))<.03,`Unstable ${JSON.stringify(row)}: ${JSON.stringify(last)}`);
    assert.ok(maxCart<2.304);assert.equal(last.boundaries,0);assert.ok(last.maxForce<=120.000001);assert.ok(last.maxForceRate<=500.000001);assert.equal(requests,0);
    records.push({source:row.source,target:row.target,runtime_sha256:row.runtime_sha256,clock:last.time,max_cart:maxCart,angle_deg:angle*180/Math.PI,max_force:last.maxForce,max_force_rate:last.maxForceRate});
    if(i%50===0)console.log('TOUR',n,i,'/',path.length-1);
  }
  report.continuous.push({order:n,edges:records.length,records,final_state:last.state,final_clock:last.time});console.log('TOUR_PASS',n,records.length);
}
report.passed=true;report.complete=!startupOnly;fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2));console.log(startupOnly?'PASS explicit startup jump then continuous strict hand-offs':'PASS all exact-bank chained references, 5 s holds, zero contacts/replans, passive rods');
