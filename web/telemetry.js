const COLORS=['#3d78e5','#e6a044','#20a895','#9b79d5','#df7d9f'];
const degrees=180/Math.PI;
export const signalDefinitions=n=>[
  {id:'theta',title:'摆臂夹角',unit:'°',range:10,series:Array.from({length:n},(_,i)=>({label:`θ${i+1}`,color:COLORS[i],get:r=>r.state[i+1]*degrees}))},
  {id:'omega',title:'角速度',unit:'°/s',range:10,series:Array.from({length:n},(_,i)=>({label:`ω${i+1}`,color:COLORS[i],get:r=>r.state[n+2+i]*degrees}))},
  {id:'position',title:'横向位移',unit:'m',range:2.6,series:[{label:'x',color:'#4384d9',get:r=>r.state[0]}]},
  {id:'velocity',title:'横向线速度',unit:'m/s',range:.5,series:[{label:'v',color:'#8d7bd2',get:r=>r.state[n+1]}]},
  {id:'force',title:'牵引力',unit:'N',range:10,series:[{label:'F',color:'#df9c42',get:r=>r.force}]},
  {id:'energy',title:'系统总机械能',unit:'J',range:1,series:[{label:'E',color:'#27a58e',get:r=>r.energy}]},
];

export class SignalBuffer{
  constructor(limit=7500){this.limit=limit;this.rows=[];}
  clear(){this.rows=[];}
  push(snapshot){
    const last=this.rows.at(-1);
    if(last&&snapshot.time<last.time-1e-8)this.clear();
    else if(last&&snapshot.time-last.time<.012)return;
    this.rows.push({time:snapshot.time,state:[...snapshot.state],force:snapshot.force,energy:snapshot.energy});
    if(this.rows.length>this.limit)this.rows.splice(0,this.rows.length-this.limit);
  }
  lowerBound(t){let lo=0,hi=this.rows.length;while(lo<hi){const mid=(lo+hi)>>1;if(this.rows[mid].time<t)lo=mid+1;else hi=mid;}return lo;}
  window(start,end){const from=Math.max(0,this.lowerBound(start)-1),to=this.lowerBound(end+1e-8);return this.rows.slice(from,to);}
  nearest(t){const i=this.lowerBound(t),a=this.rows[i-1],b=this.rows[i];return !a?b:!b?a:t-a.time<b.time-t?a:b;}
}

// Keep extrema when reducing samples to canvas resolution; spikes remain visible.
export function envelope(rows,get,maxPoints){
  if(rows.length<=maxPoints)return rows.map(r=>[r.time,get(r)]);
  const stride=Math.ceil(rows.length/(maxPoints/2)),out=[];
  for(let i=0;i<rows.length;i+=stride){let min=i,max=i;for(let j=i+1;j<Math.min(i+stride,rows.length);j++){if(get(rows[j])<get(rows[min]))min=j;if(get(rows[j])>get(rows[max]))max=j;}
    for(const j of min===max?[min]:min<max?[min,max]:[max,min])out.push([rows[j].time,get(rows[j])]);}
  return out;
}

export class TelemetryDashboard{
  constructor(root){
    this.root=root;this.grid=root.querySelector('#telemetry-grid');this.buffer=new SignalBuffer();this.windowSeconds=12;this.n=0;this.lastDraw=0;this.lastValues=0;this.hover=null;this.visible=true;this.dirty=true;this.lastReceive=0;
    this.resizeObserver=new ResizeObserver(()=>this.dirty=true);this.resizeObserver.observe(root);
    this.visibilityObserver=new IntersectionObserver(entries=>this.visible=entries[0].isIntersecting,{rootMargin:'150px'});this.visibilityObserver.observe(root);
    root.querySelector('#chart-window').onchange=e=>{this.windowSeconds=+e.target.value;this.hover=null;};
    root.querySelector('#clear-charts').onclick=()=>{this.cutoff=this.head||0;this.ranges={};this.hover=null;};this.setOrder(3);
  }
  setOrder(n){
    if(this.n===n)return;this.n=n;this.definitions=signalDefinitions(n);this.ranges={};this.dirty=true;
    this.grid.innerHTML=this.definitions.map(d=>`<article class="signal-card"><div class="signal-title"><span>${d.title}</span><small>${d.unit}</small></div><div class="signal-values" id="reading-${d.id}">—</div><canvas aria-label="${d.title}动态图表" data-signal="${d.id}"></canvas><div class="signal-legend">${d.series.map(s=>`<span><i style="background:${s.color}"></i>${s.label}</span>`).join('')}</div></article>`).join('');
    this.charts=this.definitions.map(d=>({...d,canvas:this.grid.querySelector(`[data-signal="${d.id}"]`),reading:this.grid.querySelector(`#reading-${d.id}`)}));
    for(const chart of this.charts){chart.canvas.onpointermove=e=>{const r=chart.canvas.getBoundingClientRect(),x=Math.max(0,Math.min(1,(e.clientX-r.left-31)/(r.width-41)));this.hover=Math.min(this.head||0,(this.end||12)-this.windowSeconds+x*this.windowSeconds);};chart.canvas.onpointerleave=()=>this.hover=null;}
  }
  clear(){this.buffer.clear();this.ranges={};this.hover=null;this.cutoff=0;}
  push(snapshot){this.setOrder((snapshot.state.length/2)-1);this.buffer.push(snapshot);this.lastReceive=performance.now();}
  replay(clip,model){this.buffer=new SignalBuffer();this.buffer.rows=clip.frames.map(r=>({time:r[0]-clip.frames[0][0],state:r.slice(1,-1),force:r.at(-1),energy:model.energy(r.slice(1,-1))}));this.ranges={};this.hover=null;this.cutoff=0;this.setOrder(clip.order);}
  draw(now,snapshot,replaying=false){
    if(!snapshot||(!this.visible&&!this.recording)||now-this.lastDraw<16)return;const frameDt=Math.min((now-this.lastDraw)/1000,.1);this.lastDraw=now;
    if(snapshot.time<(this.head||0)-.05)this.cutoff=0;
    this.head=snapshot.time;const drift=!replaying&&snapshot.running&&!snapshot.planning?Math.min((now-this.lastReceive)/1000,.06)*(snapshot.speed||1):0;
    this.end=Math.max(this.windowSeconds,this.head+drift);const start=this.end-this.windowSeconds,rows=this.buffer.window(Math.max(start,this.cutoff||0),this.head).filter(r=>r.time>=(this.cutoff||0)-1e-8),reading=this.hover===null?this.buffer.nearest(this.head):this.buffer.nearest(Math.max(start,this.hover));
    if(this.dirty){for(const chart of this.charts){const r=chart.canvas.getBoundingClientRect(),dpi=Math.min(devicePixelRatio||1,2.5);chart.width=r.width;chart.height=r.height;chart.canvas.width=Math.round(r.width*dpi);chart.canvas.height=Math.round(r.height*dpi);chart.context=chart.canvas.getContext('2d');chart.context.setTransform(dpi,0,0,dpi,0,0);}this.dirty=false;}
    for(const chart of this.charts){
      const c=chart.context,w=chart.width,h=chart.height;if(w<10||h<10)continue;
      const pad={l:31,r:10,t:9,b:20},ww=w-pad.l-pad.r,hh=h-pad.t-pad.b;
      let peak=0;for(const r of rows)for(const s of chart.series)peak=Math.max(peak,Math.abs(s.get(r)));
      const wanted=Math.max(chart.range,peak*1.16),previous=this.ranges[chart.id]||wanted;
      const range=Math.max(peak*1.05,previous+(wanted-previous)*(1-Math.exp(-frameDt*(wanted>previous?14:3))));this.ranges[chart.id]=range;
      const x=t=>pad.l+(t-start)/this.windowSeconds*ww,y=v=>pad.t+hh/2-v/range*hh/2;
      c.clearRect(0,0,w,h);c.font='8px Consolas';c.lineWidth=.7;c.textAlign='right';
      for(let i=0;i<3;i++){const v=range*(1-i),yy=y(v);c.strokeStyle=i===1?'#dce5f1':'#edf2f8';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(w-pad.r,yy);c.stroke();c.fillStyle='#a4b2c7';c.fillText(v.toFixed(range<5?1:0),pad.l-5,yy+3);}
      c.textAlign='center';for(let i=0;i<3;i++){const t=start+this.windowSeconds*i/2,xx=x(t);c.fillStyle='#a8b6ca';c.fillText(`${Math.round(t)}s`,xx,h-4);}
      c.save();c.beginPath();c.rect(pad.l,pad.t,ww,hh);c.clip();
      const limit=chart.id==='position'?snapshot.rail:chart.id==='force'?snapshot.forceLimit:null;
      if(limit&&limit<range){c.setLineDash([3,4]);c.strokeStyle='#e6c5a1';for(const v of [-limit,limit]){c.beginPath();c.moveTo(pad.l,y(v));c.lineTo(w-pad.r,y(v));c.stroke();}c.setLineDash([]);}
      for(const s of chart.series){const pts=envelope(rows,s.get,Math.max(20,Math.floor(ww*1.7)));if(!pts.length)continue;
        const path=new Path2D();for(let i=0;i<pts.length;i++){const [t,v]=pts[i];i?path.lineTo(x(t),y(v)):path.moveTo(x(t),y(v));}
        if(chart.series.length===1&&pts.length>1){const fill=new Path2D(path);fill.lineTo(x(pts.at(-1)[0]),y(0));fill.lineTo(x(pts[0][0]),y(0));fill.closePath();const gradient=c.createLinearGradient(0,pad.t,0,h-pad.b);gradient.addColorStop(0,s.color+'19');gradient.addColorStop(1,s.color+'02');c.fillStyle=gradient;c.fill(fill);}
        c.lineWidth=1.6;c.strokeStyle=s.color;c.lineJoin='round';c.lineCap='round';c.stroke(path);
        const end=pts.at(-1);c.beginPath();c.arc(x(end[0]),y(end[1]),2.2,0,Math.PI*2);c.fillStyle=s.color;c.fill();
      }
      if(this.hover!==null&&reading){c.strokeStyle='#a6b9d5';c.lineWidth=.8;c.setLineDash([2,3]);c.beginPath();c.moveTo(x(reading.time),pad.t);c.lineTo(x(reading.time),h-pad.b);c.stroke();c.setLineDash([]);for(const s of chart.series){c.beginPath();c.arc(x(reading.time),y(s.get(reading)),3,0,Math.PI*2);c.fillStyle='white';c.fill();c.strokeStyle=s.color;c.stroke();}}
      c.restore();
      if(reading&&now-this.lastValues>45){const digits=chart.series.length>1?0:chart.id==='energy'?2:chart.id==='force'?1:2;
        chart.reading.innerHTML=chart.series.map(s=>{const value=s.get(reading),display=Math.abs(value)<.5*10**(-digits)?0:value;return `<span style="color:${s.color}">${display.toFixed(digits)}<small>${chart.series.length>1?s.label:chart.unit}</small></span>`;}).join('');}
    }
    if(now-this.lastValues>45){this.root.querySelector('#chart-cursor').textContent=this.hover===null?'悬停曲线 · 同步读取六组数据':`t = ${reading?.time.toFixed(3)||'—'} s`;this.lastValues=now;}
  }
}
