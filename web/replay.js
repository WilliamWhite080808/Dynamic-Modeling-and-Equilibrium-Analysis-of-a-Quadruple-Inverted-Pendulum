import {Physics,clamp} from './physics.js';
import {STABLE_HOLD_SECONDS} from './experiment.js';

export class ReplayPlayer{
  constructor(){this.loop=false;this.clip=null;this.time=0;this.playing=false;this.speed=1;this.epoch=-1;}
  load(clip){
    const dim=2*(clip.order+1);
    if(!clip.frames||clip.frames.length<2||clip.frames.some((r,i)=>r.length!==dim+2||!r.every(Number.isFinite)||(i>0&&r[0]<=clip.frames[i-1][0])))throw Error('轨迹复现数据不完整或时间戳不连续');
    this.clip=clip;this.model=new Physics(clip.design);this.offset=clip.frames[0][0];this.duration=clip.frames.at(-1)[0]-this.offset;
    this.time=0;this.playing=true;this.epoch--;this.speed=1;
  }
  seek(value){this.time=clamp(value,0,this.duration||0);}
  advance(dt){if(this.playing){this.seek(this.time+Math.max(0,dt)*this.speed);if(this.loop&&this.time>=Math.min(this.duration,Math.max(0,(this.clip.settled_at||0)-this.offset)+STABLE_HOLD_SECONDS)){this.time=0;this.epoch--;}else if(this.time>=this.duration)this.playing=false;}}
  snapshot(){
    if(!this.clip)return null;
    const f=this.clip.frames,t=this.offset+this.time;let lo=0,hi=f.length-1;
    while(lo+1<hi){const mid=(lo+hi)>>1;if(f[mid][0]<=t)lo=mid;else hi=mid;}
    const a=clamp((t-f[lo][0])/(f[hi][0]-f[lo][0]),0,1),dim=this.model.dim;
    const state=Array.from({length:dim},(_,i)=>f[lo][i+1]*(1-a)+f[hi][i+1]*a);
    const force=f[lo][dim+1]*(1-a)+f[hi][dim+1]*a;
    return {type:'state',state,estimate:[...state],time:this.time,force,rawForce:force,target:this.clip.target||0,stage:'replay',planning:false,running:this.playing,speed:this.speed,stable:Math.max(0,t-(this.clip.settled_at||0)),attempt:0,boundaries:0,maxForce:0,saturation:0,energy:this.model.energy(state),physicsMs:0,controlMs:0,observerMs:0,cycleMs:0,lag:0,reason:'',epoch:this.epoch,history:[]};
  }
}

function db(){return new Promise((resolve,reject)=>{const r=indexedDB.open('pendulum-lab-replays',1);r.onupgradeneeded=()=>r.result.createObjectStore('successes',{keyPath:'order'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
export async function saveSuccess(clip){const connection=await db();return new Promise((resolve,reject)=>{const t=connection.transaction('successes','readwrite');t.objectStore('successes').put(clip);t.oncomplete=()=>{connection.close();resolve();};t.onerror=()=>{connection.close();reject(t.error);};});}
export async function loadSuccess(order){const connection=await db();return new Promise((resolve,reject)=>{const t=connection.transaction('successes');const r=t.objectStore('successes').get(order);r.onsuccess=()=>{connection.close();resolve(r.result);};r.onerror=()=>{connection.close();reject(r.error);};});}
