import fs from 'node:fs';
import assert from 'node:assert/strict';
import {Physics,wrap,clamp} from '../web/physics.js';
const designs=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const reports=[];
for(const design of designs){
  const n=design.parameters.n,plan=JSON.parse(fs.readFileSync(`results/verified-${n}.json`,'utf8')),p=new Physics(design),d=p.d;
  let s=[...plan.initial],u=0,time=0,maxCart=0,maxForce=0,contacts=0,stable=0,settled=null;
  const total=plan.duration+10;
  for(let tick=0;tick<total*1000;tick++){
    if(tick%4===0){
      if(time<plan.duration){
        const z=time/plan.dt,k=Math.min(Math.floor(z),plan.states.length-2),a=z-k;
        const ref=plan.states[k].map((v,i)=>(2*a**3-3*a*a+1)*v+(a**3-2*a*a+a)*plan.dt*plan.derivatives[k][i]+(-2*a**3+3*a*a)*plan.states[k+1][i]+(a**3-a*a)*plan.dt*plan.derivatives[k+1][i]);
        const gain=plan.gains[k].map((v,i)=>v*(1-a)+plan.gains[k+1][i]*a);
        const deviation=s.map((v,i)=>i>0&&i<d?wrap(v-ref[i]):v-ref[i]);
        u=plan.forces[k]*(1-a)+plan.forces[k+1]*a-gain.reduce((sum,k,i)=>sum+k*deviation[i],0);
      }else{
        const error=s.map((v,i)=>i>0&&i<d?wrap(v):v);u=-p.K.reduce((sum,k,i)=>sum+k*error[i],0);
      }
      u=clamp(u,-p.p.max_force,p.p.max_force);
    }
    s=p.step(s,u,.001);if(p.contact(s))contacts++;time+=.001;
    maxCart=Math.max(maxCart,Math.abs(s[0]));maxForce=Math.max(maxForce,Math.abs(u));
    const angle=Math.max(...s.slice(1,d).map(v=>Math.abs(wrap(v))))*180/Math.PI;
    const isStable=angle<.5&&Math.max(...s.slice(d+1).map(Math.abs))<.03&&Math.abs(s[0])<.03;
    stable=isStable?stable+.001:0;if(stable>=1&&settled===null)settled=time-1;
  }
  const angle=Math.max(...s.slice(1,d).map(v=>Math.abs(wrap(v))))*180/Math.PI;
  const report={order:n,angle_deg:angle,cart_m:s[0],max_cart_m:maxCart,peak_force_N:maxForce,contacts,settled_at:settled};reports.push(report);
  console.log(JSON.stringify(report));
  assert.ok(angle<.5&&Math.abs(s[0])<.03&&stable>1,`N=${n} did not stabilize`);
  assert.equal(contacts,0);assert.ok(maxCart<p.p.rail);assert.ok(maxForce<=p.p.max_force);
}
fs.writeFileSync('results/browser-physics-acceptance.json',JSON.stringify(reports,null,2));
