import fs from 'node:fs';
import assert from 'node:assert/strict';
import {Physics,Estimate} from '../web/physics.js';
const fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
for(const f of fixtures){
  const p=new Physics(f.design);
  for(const [actual,expected] of [[p.rhs(f.s,7),f.rhs],[p.step(f.s,7,.001),f.step]])
    actual.forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<1e-10,`N=${p.n}: ${v} != ${expected[i]}`));
  const state=[...f.s];state[0]=p.p.rail+.01;state[p.d]=3;
  const before=p.energy(state);assert.equal(p.contact(state),true);
  assert.ok(state[0]<=p.p.rail);assert.ok(state[p.d]<0);assert.ok(p.energy(state)<=before+1e-9);
  const o=new Estimate(p,'cart_and_tip','ekf');o.update(p.measure(f.s,'cart_and_tip'),7,.004,.002);assert.ok(o.x.every(Number.isFinite));
}
console.log('JS / Python dynamics, RK4 and passive rail impact: orders 1..5 PASS');
