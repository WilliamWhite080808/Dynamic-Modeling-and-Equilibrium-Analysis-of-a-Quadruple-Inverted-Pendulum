const palette=['#3478ef','#f2a13c','#19ab9a','#a275df','#e6719b'];
const round=(c,x,y,w,h,r)=>{c.beginPath();c.roundRect(x,y,w,h,r);};
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
export class Renderer{
  constructor(canvas){this.canvas=canvas;this.camera=null;this.trail=[];this.last=-1;this.lastEpoch=-1;}
  reset(){this.camera=null;this.trail=[];this.last=-1;}
  size(){const r=this.canvas.getBoundingClientRect(),dpi=Math.min(devicePixelRatio||1,3),w=Math.round(r.width*dpi),h=Math.round(r.height*dpi);if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;}const c=this.canvas.getContext('2d');c.setTransform(dpi,0,0,dpi,0,0);return[c,r.width,r.height];}
  draw({design,snapshot,hidden=false,ghost=false,trail=true}){
    const[c,w,h]=this.size();c.clearRect(0,0,w,h);if(!design||!snapshot)return null;
    const n=design.parameters.n,p=design.parameters,sum=design.lengths.reduce((a,b)=>a+b,0);
    if(this.lastEpoch!==snapshot.epoch){this.reset();this.lastEpoch=snapshot.epoch;}
    const points=s=>{let x=s[0],y=0;const a=[[x,y]];for(let i=0;i<n;i++){x+=design.lengths[i]*Math.sin(s[i+1]);y+=design.lengths[i]*Math.cos(s[i+1]);a.push([x,y]);}return a;};
    const real=points(snapshot.state),estimated=points(snapshot.estimate),visible=hidden?[[0,-sum],[0,sum]]:real;
    const halfWidth=Math.min(1,Math.max(.55,sum*.38));
    const bounds={l:Math.min(snapshot.state[0]-halfWidth,...visible.map(v=>v[0]))-.22,r:Math.max(snapshot.state[0]+halfWidth,...visible.map(v=>v[0]))+.22,b:Math.min(0,...visible.map(v=>v[1]))-.25,t:Math.max(0,...visible.map(v=>v[1]))+.25};
    if(!this.camera)this.camera={...bounds};
    // Expand immediately to keep everything in frame; ease inward after motion settles.
    for(const k of ['l','r','b','t']){const value=this.camera[k]+(bounds[k]-this.camera[k])*.014;this.camera[k]=(k==='l'||k==='b')?Math.min(bounds[k],value):Math.max(bounds[k],value);}
    const cam=this.camera,top=88,bottom=96,scale=Math.min((w-65)/(cam.r-cam.l),(h-top-bottom)/(cam.t-cam.b));
    const center=w/2-(cam.l+cam.r)/2*scale,base=top+(h-top-bottom)/2+(cam.t+cam.b)/2*scale;
    const px=x=>center+x*scale,py=y=>base-y*scale,screen=a=>a.map(v=>[px(v[0]),py(v[1])]);
    const actual=screen(real),estimate=screen(estimated);
    const bg=c.createLinearGradient(0,0,w,h);bg.addColorStop(0,'#ffffff');bg.addColorStop(1,'#f4f8fe');c.fillStyle=bg;c.fillRect(0,0,w,h);
    const step=Math.max(25,scale*.5);c.strokeStyle='#e8eef7';c.lineWidth=.7;
    for(let x=center%step;x<w;x+=step){c.beginPath();c.moveTo(x,0);c.lineTo(x,h);c.stroke();}
    for(let y=base%step;y<h;y+=step){c.beginPath();c.moveTo(0,y);c.lineTo(w,y);c.stroke();}
    // Upright reference axis is a visual guide, not a constraint on the rods.
    c.strokeStyle='#c5d8f3';c.setLineDash([5,6]);c.lineWidth=1;c.beginPath();c.moveTo(px(snapshot.target),top-10);c.lineTo(px(snapshot.target),h-43);c.stroke();c.setLineDash([]);
    const lx=px(-p.rail),rx=px(p.rail),railY=base+30;
    c.shadowColor='#48678920';c.shadowBlur=14;c.shadowOffsetY=6;c.fillStyle='#dce4ef';round(c,lx-8,railY,rx-lx+16,13,6);c.fill();c.shadowBlur=0;c.shadowOffsetY=0;
    const railGradient=c.createLinearGradient(0,railY,0,railY+10);railGradient.addColorStop(0,'#f8fafc');railGradient.addColorStop(.4,'#adbdcf');railGradient.addColorStop(1,'#d9e3ee');c.fillStyle=railGradient;round(c,lx-7,railY+1,rx-lx+14,8,4);c.fill();
    c.lineWidth=1;c.strokeStyle='#93abc8';c.beginPath();c.moveTo(lx,railY+2);c.lineTo(rx,railY+2);c.stroke();
    // Symmetric, readable SI ticks.
    for(let x=Math.ceil(-p.rail*2)/2;x<=p.rail;x+=.5){c.strokeStyle='#b4c4d9';c.beginPath();c.moveTo(px(x),railY+18);c.lineTo(px(x),railY+23);c.stroke();c.fillStyle='#91a3bd';c.font='10px Consolas';c.textAlign='center';c.fillText(x.toFixed(1),px(x),railY+37);}
    for(const sign of [-1,1]){
      const x=px(sign*p.rail);
      if(x<12||x>w-12){c.fillStyle='#a88049';c.font='10px Consolas';c.textAlign=sign<0?'left':'right';c.fillText(`${sign<0?'← ':''}轨道端 ${sign<0?'−':'+'}${p.rail.toFixed(1)} m${sign>0?' →':''}`,sign<0?15:w-15,base-22);continue;}
      const gradient=c.createLinearGradient(x-5,0,x+5,0);gradient.addColorStop(0,'#546a87');gradient.addColorStop(.5,'#91a3bb');gradient.addColorStop(1,'#526984');c.fillStyle=gradient;round(c,x-5,base-9,10,55,3);c.fill();
      c.fillStyle='#f1ac4f';round(c,x-5,base-4,10,4,1);c.fill();round(c,x-5,base+8,10,4,1);c.fill();
      c.fillStyle='#a88049';c.font='10px Consolas';c.textAlign='center';c.fillText(`${sign>0?'+':'−'}${p.rail.toFixed(1)} m`,x,base-22);
    }
    const target=clamp(px(snapshot.target),24,w-24);c.fillStyle='#508e71';c.beginPath();c.moveTo(target,railY+51);c.lineTo(target-5,railY+58);c.lineTo(target+5,railY+58);c.fill();c.font='9px Consolas';c.textAlign='center';c.fillText('目标位置',target,railY+72);
    if(trail&&!hidden){
      if(snapshot.running&&!snapshot.planning&&this.last!==snapshot.time){this.trail.push({p:real.at(-1),t:snapshot.time});this.last=snapshot.time;}
      this.trail=this.trail.filter(a=>snapshot.time-a.t<3.5).slice(-400);
      for(let i=1;i<this.trail.length;i++){c.strokeStyle=`rgba(52,120,239,${.03+i/this.trail.length*.25})`;c.lineWidth=1.7;c.beginPath();c.moveTo(px(this.trail[i-1].p[0]),py(this.trail[i-1].p[1]));c.lineTo(px(this.trail[i].p[0]),py(this.trail[i].p[1]));c.stroke();}
    }else this.trail=[];
    const cart=actual[0],cw=Math.max(48,scale*.42),ch=28;
    c.shadowColor='#47638b2b';c.shadowBlur=15;c.shadowOffsetY=6;
    const cg=c.createLinearGradient(0,base+2,0,base+ch);cg.addColorStop(0,'#5d7fae');cg.addColorStop(1,'#2c4c78');c.fillStyle=cg;round(c,cart[0]-cw/2,base+1,cw,ch,6);c.fill();c.shadowBlur=0;c.shadowOffsetY=0;
    c.fillStyle='#e6eef9';round(c,cart[0]-cw/2+7,base+6,cw-14,8,2);c.fill();c.fillStyle='#a5c1e7';round(c,cart[0]-cw/2+11,base+18,cw-22,3,1);c.fill();
    for(const offset of [-cw*.3,cw*.3]){c.fillStyle='#354b6b';c.beginPath();c.arc(cart[0]+offset,base+30,6,0,Math.PI*2);c.fill();c.fillStyle='#bacce2';c.beginPath();c.arc(cart[0]+offset,base+30,2.5,0,Math.PI*2);c.fill();}
    c.fillStyle='#e7eef8';c.strokeStyle='#5679ab';c.lineWidth=2;c.beginPath();c.arc(cart[0],base,6,0,Math.PI*2);c.fill();c.stroke();
    if(ghost){c.globalAlpha=.6;c.strokeStyle='#7d9abb';c.lineWidth=4;c.setLineDash([6,5]);for(let i=0;i<n;i++){c.beginPath();c.moveTo(...estimate[i]);c.lineTo(...estimate[i+1]);c.stroke();}c.setLineDash([]);c.globalAlpha=1;}
    if(!hidden){
      for(let i=0;i<n;i++){
        const a=actual[i],b=actual[i+1];c.lineCap='round';
        c.shadowColor='#344d7835';c.shadowBlur=9;c.shadowOffsetY=4;c.strokeStyle=palette[i];c.lineWidth=10;c.beginPath();c.moveTo(...a);c.lineTo(...b);c.stroke();c.shadowBlur=0;c.shadowOffsetY=0;
        c.globalAlpha=.65;c.strokeStyle='#fff';c.lineWidth=2;c.beginPath();c.moveTo(a[0]-1.5,a[1]-1);c.lineTo(b[0]-1.5,b[1]-1);c.stroke();c.globalAlpha=1;
        const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2;
        const angle=Math.atan2(Math.sin(snapshot.state[i+1]),Math.cos(snapshot.state[i+1]))*180/Math.PI;
        const text=`θ${i+1}  ${angle.toFixed(1)}°`;c.font='11px Consolas';const tw=c.measureText(text).width;
        const tx=clamp(mx+15,9,w-tw-19),ty=clamp(my-10,78,h-65);c.fillStyle='#ffffffef';round(c,tx-5,ty-11,tw+10,20,4);c.fill();c.fillStyle=palette[i];c.textAlign='left';c.fillText(text,tx,ty+3);
      }
      for(let i=0;i<actual.length;i++){
        const a=actual[i],color=palette[Math.max(0,i-1)],radius=i===actual.length-1?8:9;
        c.shadowColor='#2a456d20';c.shadowBlur=6;c.shadowOffsetY=2;c.fillStyle='#fff';c.beginPath();c.arc(...a,radius,0,Math.PI*2);c.fill();c.shadowBlur=0;c.shadowOffsetY=0;
        c.strokeStyle=color;c.lineWidth=2.5;c.stroke();c.fillStyle='#526d92';c.beginPath();c.arc(...a,3,0,Math.PI*2);c.fill();
      }
    }
    if(Math.abs(snapshot.force)>.5){const dir=Math.sign(snapshot.force),len=20+Math.abs(snapshot.force)/p.max_force*45,x=cart[0]+dir*(cw/2+13),y=base+15;c.strokeStyle='#de8e27';c.lineWidth=3;c.beginPath();c.moveTo(x,y);c.lineTo(x+dir*len,y);c.lineTo(x+dir*(len-7),y-5);c.moveTo(x+dir*len,y);c.lineTo(x+dir*(len-7),y+5);c.stroke();c.fillStyle='#bd811f';c.font='10px Consolas';c.textAlign='center';c.fillText(`${snapshot.force.toFixed(1)} N`,x+dir*len/2,y-13);}
    c.lineCap='butt';c.shadowBlur=0;c.shadowOffsetY=0;
    // Global overview makes finite rail limits visible even in the close-up camera.
    const mapW=95,mapX=25,mapY=h-48;
    c.strokeStyle='#c9d7e9';c.lineWidth=3;c.beginPath();c.moveTo(mapX,mapY);c.lineTo(mapX+mapW,mapY);c.stroke();
    for(const xx of [mapX,mapX+mapW]){c.strokeStyle='#d3a967';c.lineWidth=2;c.beginPath();c.moveTo(xx,mapY-5);c.lineTo(xx,mapY+5);c.stroke();}
    c.fillStyle='#3478ef';round(c,mapX+(snapshot.state[0]+p.rail)/(2*p.rail)*mapW-4,mapY-4,8,8,2);c.fill();
    c.fillStyle='#8a9fb8';c.font='9px Consolas';c.textAlign='left';c.fillText('全轨道 · 自动跟随',mapX+mapW+12,mapY+3);
    return {scale,center,base};
  }
}
