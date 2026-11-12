export function patternsFor(order){
  if(!Number.isInteger(order)||order<1||order>5)throw Error('阶数需要为 1～5');
  return Array.from({length:2**order-1},(_,i)=>i.toString(2).padStart(order,'0').replaceAll('0','U').replaceAll('1','D'));
}
export function equilibriaFor(order){return [...patternsFor(order),'D'.repeat(order)];}
