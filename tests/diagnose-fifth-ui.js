window.__recordProbe={results:[]};
document.querySelector('#orders [data-order="5"]').click();
let rate=document.querySelector('#speed');rate.value=3;rate.dispatchEvent(new Event('change',{bubbles:true}));
let count=0;let timer=setInterval(()=>{
window.__recordProbe.results.push({selected:document.querySelector('#orders .selected')?.dataset.order,disabled:document.querySelector('#orders [data-order="5"]').disabled,from:document.querySelector('#transfer-from').value,note:document.querySelector('#transfer-note').textContent,stable:document.querySelector('#stable-metric').textContent,angle:document.querySelector('#angle-metric').textContent,dimension:document.querySelector('#dimension').textContent,loading:document.querySelector('#loading').classList.contains('hidden')});
if(++count>=20){clearInterval(timer);window.__recordProbe.done=true;}
},300);
