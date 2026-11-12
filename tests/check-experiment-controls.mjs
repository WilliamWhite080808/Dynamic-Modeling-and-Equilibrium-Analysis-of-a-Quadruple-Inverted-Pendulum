import fs from 'node:fs';
import assert from 'node:assert/strict';
import {simulationRate,timelineEnd} from '../web/experiment.js';
const f=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let clock=0,timer,last,seek,loops=[];
Object.defineProperty(globalThis,'performance',{value:{now:()=>clock},configurable:true});
globalThis.setInterval=cb=>timer=cb;globalThis.onmessage=null;
globalThis.postMessage=m=>{if(m.type==='state')last=m;if(m.type==='seek-complete')seek=m;if(m.type==='trajectory-restarted')loops.push(m);};
await import('../web/sim-worker.js');
const send=data=>globalThis.onmessage({data});
function advance(seconds){for(let i=0;i<Math.round(seconds*250);i++){clock+=4;timer();}}
function begin(loop=false){send({type:'play-transition',design:f.design,plan:f.plan,loop,request_id:'test'});send({type:'settings',speed:1});}
assert.equal(simulationRate(.01),.1);assert.equal(simulationRate(12),10);assert.equal(simulationRate(.731),.731);
assert.equal(timelineEnd(f.plan),f.plan.verification.settled_at+.5);
begin();advance(2);const at2=structuredClone(last);advance(1);const at3=structuredClone(last);
send({type:'seek',time:2,running:false,request_id:1});assert.equal(seek.request_id,1);assert.ok(!last.running);assert.equal(last.time,at2.time);assert.deepEqual(last.state,at2.state);assert.equal(last.force,at2.force);assert.ok(last.epoch>at2.epoch);assert.ok(seek.signals.length>150);
send({type:'settings',running:true});advance(1);assert.deepEqual(last.state,at3.state);assert.equal(last.force,at3.force);
send({type:'seek',time:1e6,running:false,request_id:2});assert.ok(Math.abs(last.time-last.timeline.end)<.00101);assert.ok(last.stable>=.49);
begin();send({type:'settings',speed:.1});advance(1);assert.ok(Math.abs(last.time-.1)<.002);
begin();send({type:'settings',speed:10});advance(1);assert.ok(Math.abs(last.time-10)<.002);assert.equal(last.boundaries,0);assert.ok(last.maxForce<=120);
begin(true);advance(12);assert.equal(loops.length,0,'Do not restart before 10 seconds of stable holding');advance(8);
assert.equal(loops.length,1);assert.ok(loops[0].held_for>=10);assert.equal(last.timeline.cycle,1);assert.ok(last.time<8);
send({type:'settings',running:false});const stopped=last.time;advance(3);assert.equal(last.time,stopped);
console.log('PASS: exact physical seek/resume, steady+0.5s timeline, continuous 0.1–10x rates, stable-10s repetition, stopped state and bounded cart force.');
