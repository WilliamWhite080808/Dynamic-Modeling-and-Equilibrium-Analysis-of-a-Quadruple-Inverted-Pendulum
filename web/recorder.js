// Native canvas capture: only the scientific scene, readouts and charts enter
// the stream. Browser chrome, dialogs and operation controls are excluded.
const box=(c,r,origin,fill='#fff')=>{const x=r.left-origin.left,y=r.top-origin.top;c.fillStyle=fill;c.strokeStyle='#e1e7f0';c.lineWidth=1;c.beginPath();c.roundRect(x,y,r.width,r.height,11);c.fill();c.stroke();return[x,y];};
export class CoreRecorder{
  constructor(root,button,notice){this.root=root;this.button=button;this.notice=notice;this.recording=false;this.lastFrame=0;this.downloadLink=document.createElement('a');this.downloadLink.className='record-download hidden';this.downloadLink.textContent='保存录制文件';button.after(this.downloadLink);button.onclick=()=>this.recording?this.stop():this.start();}
  bounds(){const r=this.root.getBoundingClientRect(),scene=this.root.querySelector('#arena').getBoundingClientRect(),charts=this.root.querySelector('.telemetry-dashboard').getBoundingClientRect();return{left:r.left,top:r.top,width:r.width,height:Math.max(scene.bottom,charts.bottom)-r.top};}
  start(){
    if(typeof MediaRecorder==='undefined'||!HTMLCanvasElement.prototype.captureStream){this.notice('当前浏览器暂不支持核心区域录制。');return;}
    try{
      if(this.outputUrl)URL.revokeObjectURL(this.outputUrl);this.downloadLink.classList.add('hidden');
      const r=this.bounds();this.scale=Math.min(2,1920/r.width,1080/r.height);this.canvas=document.createElement('canvas');this.canvas.width=Math.round(r.width*this.scale);this.canvas.height=Math.round(r.height*this.scale);this.context=this.canvas.getContext('2d');
      this.draw();this.stream=this.canvas.captureStream(30);this.chunks=[];
      const mime=['video/webm;codecs=vp8','video/webm;codecs=vp9','video/webm','video/mp4'].find(v=>MediaRecorder.isTypeSupported(v));
      const chunks=this.chunks,encoder=this.encoder=new MediaRecorder(this.stream,{...(mime?{mimeType:mime}:{}),videoBitsPerSecond:6000000});
      this.encoder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      this.encoder.onstop=async()=>{const type=encoder.mimeType||'video/webm',blob=new Blob(chunks,{type});this.outputUrl=URL.createObjectURL(blob);let fileUrl=this.outputUrl;try{const response=await fetch('/api/recordings',{method:'POST',headers:{'Content-Type':type},body:blob});if(response.ok)fileUrl=(await response.json()).url;}catch{}this.downloadLink.href=fileUrl;this.downloadLink.download=`pendulum-core-${new Date().toISOString().replace(/[:.]/g,'-')}.${type.includes('mp4')?'mp4':'webm'}`;this.downloadLink.textContent=`保存录制文件 · ${(blob.size/1048576).toFixed(1)} MB`;this.downloadLink.classList.remove('hidden');this.downloadLink.click();chunks.length=0;encoder.ondataavailable=null;encoder.onstop=null;encoder.onerror=null;this.notice('核心区域录制已完成；若浏览器未自动保存，可点击“保存录制文件”。');};
      this.encoder.onerror=()=>{this.notice('录制发生错误，请结束后重试。');this.stop();};
      this.recording=true;this.started=performance.now();this.button.classList.add('recording');this.button.setAttribute('aria-pressed','true');this.encoder.start(1000);this.notice('正在录制核心区域，操作栏和浏览器界面不会进入画面。');
    }catch(error){this.stream?.getTracks().forEach(t=>t.stop());this.notice('无法启动录制：'+error.message);}
  }
  stop(){if(!this.recording)return;this.recording=false;if(this.encoder.state!=='inactive')this.encoder.stop();this.stream.getTracks().forEach(t=>t.stop());this.button.classList.remove('recording');this.button.setAttribute('aria-pressed','false');this.button.textContent='● 录制核心区';}
  frame(now){if(!this.recording||now-this.lastFrame<1000/30)return;this.lastFrame=now;this.draw();const seconds=Math.floor((now-this.started)/1000);this.button.textContent=`■ 结束录制 ${Math.floor(seconds/60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`;}
  draw(){
    const c=this.context,r=this.bounds(),scale=Math.min(this.canvas.width/r.width,this.canvas.height/r.height);c.setTransform(1,0,0,1,0,0);c.fillStyle='#f4f6fa';c.fillRect(0,0,this.canvas.width,this.canvas.height);c.setTransform(scale,0,0,scale,(this.canvas.width-r.width*scale)/2,(this.canvas.height-r.height*scale)/2);c.textBaseline='alphabetic';c.textAlign='left';
    const text=(value,x,y,size=12,color='#425473',weight='400')=>{c.font=`${weight} ${size}px "Segoe UI","Microsoft YaHei",sans-serif`;c.fillStyle=color;c.fillText(value,x,y);};
    const metric=this.root.querySelector('.metrics');if(metric){box(c,metric.getBoundingClientRect(),r);for(const cell of metric.children){const b=cell.getBoundingClientRect(),x=b.left-r.left+14,y=b.top-r.top;text(cell.querySelector('span').textContent,x,y+11,10,'#8390a6');text(cell.querySelector('strong').textContent,x,y+44,23,'#304a70');}}
    const arena=this.root.querySelector('#arena'),a=arena.getBoundingClientRect(),ax=a.left-r.left,ay=a.top-r.top;c.save();c.beginPath();c.roundRect(ax,ay,a.width,a.height,11);c.clip();c.drawImage(arena,ax,ay,a.width,a.height);c.restore();
    text(this.root.querySelector('#canvas-mode').textContent,ax+21,ay+24,10,'#6b85a5');text([...this.root.querySelector('#legend').children].map(v=>v.textContent).join('  '),ax+21,ay+48,11,'#5279ab');
    const dash=this.root.querySelector('.telemetry-dashboard');box(c,dash.getBoundingClientRect(),r);const dr=dash.getBoundingClientRect();text('实时状态曲线',dr.left-r.left+17,dr.top-r.top+37,15,'#3e577c','600');
    for(const card of this.root.querySelectorAll('.signal-card')){
      const b=card.getBoundingClientRect(),x=b.left-r.left,y=b.top-r.top;box(c,b,r);text(card.querySelector('.signal-title>span').textContent,x+13,y+23,11,'#7b8fae');
      let tx=x+13;for(const value of card.querySelector('.signal-values').children){text(value.textContent,tx,y+48,13,value.style.color||'#5279ab');tx+=c.measureText(value.textContent).width+9;}
      const chart=card.querySelector('canvas'),cr=chart.getBoundingClientRect();c.drawImage(chart,cr.left-r.left,cr.top-r.top,cr.width,cr.height);text([...card.querySelector('.signal-legend').children].map(v=>v.textContent).join('  '),x+13,y+b.height-7,9,'#8398b5');
    }
    const footerY=r.height-8;text('Pendulum Lab · '+document.querySelector('#order-title').textContent,ax+12,footerY,10,'#8390a6');
  }
}
