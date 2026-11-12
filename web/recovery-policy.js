export function dissipativeForce(state,elapsed,p,policy){
  const d=state.length/2,x=state[0],v=state[d],spring=.4*p.max_force,damper=.6*p.max_force;
  const position=policy.kx*(x+.5*x*x*x/(p.rail*p.rail));
  let force=-spring*Math.tanh(position/spring)-damper*Math.tanh(policy.kv*v/damper);
  if(elapsed<.6)force+=(policy.kick||0)*Math.sin(2*Math.PI*elapsed/.6)*Math.sin(Math.PI*elapsed/.6)**2;
  return Math.max(-p.max_force,Math.min(p.max_force,force));
}
