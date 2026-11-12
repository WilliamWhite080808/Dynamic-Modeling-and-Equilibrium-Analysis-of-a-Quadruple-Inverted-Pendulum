import {equilibriaFor} from './targets.js';

export function eulerTour(order,start){
  const vertices=equilibriaFor(order);
  if(order>4||!vertices.includes(start))throw Error('无效序列演示起点');
  const edges=new Map(vertices.map(a=>[a,vertices.filter(b=>b!==a).reverse()]));
  const stack=[start],path=[];
  while(stack.length){const a=stack.at(-1),out=edges.get(a);if(out.length)stack.push(out.pop());else path.push(stack.pop());}
  return path.reverse();
}

export const poseArrows=code=>code.replaceAll('U','↑').replaceAll('D','↓');
