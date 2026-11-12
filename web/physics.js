// Shared by the Web Worker and the independent Node regression tests.
// Angles are absolute, clockwise from upright. Only generalized force 0 is actuated.
export const wrap = x => Math.atan2(Math.sin(x),Math.cos(x));
export const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
export const zeros = (r,c) => Array.from({length:r},()=>Array(c).fill(0));
export const eye = n => zeros(n,n).map((r,i)=>(r[i]=1,r));
export const tr = A => A[0].map((_,j)=>A.map(r=>r[j]));
export const mm = (A,B) => A.map(r=>B[0].map((_,j)=>r.reduce((v,a,k)=>v+a*B[k][j],0)));
export const mv = (A,x) => A.map(r=>r.reduce((v,a,k)=>v+a*x[k],0));
export const add = (A,B) => A.map((r,i)=>r.map((a,j)=>a+B[i][j]));
export function solve(A,b){
  const n=b.length, M=A.map((r,i)=>[...r,b[i]]);
  for(let k=0;k<n;k++){
    let p=k;for(let i=k+1;i<n;i++)if(Math.abs(M[i][k])>Math.abs(M[p][k]))p=i;
    [M[k],M[p]]=[M[p],M[k]];
    if(Math.abs(M[k][k])<1e-14) throw Error('质量矩阵奇异');
    for(let i=k+1;i<n;i++){let a=M[i][k]/M[k][k];for(let j=k+1;j<=n;j++)M[i][j]-=a*M[k][j];}
  }
  const x=Array(n).fill(0);for(let i=n-1;i>=0;i--){let s=M[i][n];for(let j=i+1;j<n;j++)s-=M[i][j]*x[j];x[i]=s/M[i][i];}return x;
}

export class Physics{
  constructor(design){Object.assign(this,design);this.p=design.parameters;this.n=this.p.n;this.d=this.n+1;this.dim=2*this.d;this.target_angles=design.target_angles||Array(this.n).fill(0);this.total=this.p.cart_mass+this.masses.reduce((a,b)=>a+b,0);}
  matrix(s){
    const {n,d,H,a,total}=this,M=zeros(d,d);M[0][0]=total;
    for(let i=0;i<n;i++){
      M[0][i+1]=M[i+1][0]=a[i]*Math.cos(s[i+1]);
      for(let j=0;j<n;j++)M[i+1][j+1]=H[i][j]*Math.cos(s[i+1]-s[j+1]);
    }return M;
  }
  rhs(s,u,tipForce=0){
    const {n,d,p,H,a}=this,M=this.matrix(s),b=Array(d).fill(0);b[0]=u-p.cart_damping*s[d]+tipForce;
    for(let i=0;i<n;i++){
      const vi=s[d+i+1];b[0]+=a[i]*Math.sin(s[i+1])*vi*vi;
      b[i+1]=p.gravity*a[i]*Math.sin(s[i+1])+tipForce*this.lengths[i]*Math.cos(s[i+1]);
      for(let j=0;j<n;j++) b[i+1]-=H[i][j]*Math.sin(s[i+1]-s[j+1])*s[d+j+1]**2;
      b[i+1]-=p.damping*(vi-(i?s[d+i]:0));
      if(i<n-1)b[i+1]+=p.damping*(s[d+i+2]-vi);
    }
    return [...s.slice(d),...solve(M,b)];
  }
  step(s,u,dt,tip=0){
    const k1=this.rhs(s,u,tip), k2=this.rhs(s.map((v,i)=>v+dt/2*k1[i]),u,tip),
      k3=this.rhs(s.map((v,i)=>v+dt/2*k2[i]),u,tip),k4=this.rhs(s.map((v,i)=>v+dt*k3[i]),u,tip);
    const out=s.map((v,i)=>v+dt/6*(k1[i]+2*k2[i]+2*k3[i]+k4[i]));
    return out;
  }
  contact(s){
    if(Math.abs(s[0])<=this.p.rail)return false;
    const sign=Math.sign(s[0]); s[0]=sign*this.p.rail;
    if(sign*s[this.d]>0){
      const normal=Array(this.d).fill(0);normal[0]=1;
      const direction=solve(this.matrix(s),normal);
      const impulse=-(1.05)*s[this.d]/direction[0];
      for(let j=0;j<this.d;j++)s[this.d+j]+=direction[j]*impulse;
    }return true;
  }
  energy(s){const M=this.matrix(s),v=s.slice(this.d);return 0.5*v.reduce((sum,vi,i)=>sum+vi*M[i].reduce((t,m,j)=>t+m*v[j],0),0)+this.p.gravity*this.a.reduce((e,a,i)=>e+a*Math.cos(s[i+1]),0);}
  measure(s,mode){if(mode==='full_state')return [...s];if(mode==='angles_only')return s.slice(0,this.d);if(mode==='cart_only')return [s[0]];return [s[0],s[0]+this.lengths.reduce((v,l,i)=>v+l*Math.sin(s[i+1]),0)];}
}

export class Estimate{
  constructor(physics,mode,kind,bias=0){this.model=physics;this.mode=mode;this.kind=kind;this.x=Array(physics.dim).fill(0);this.P=eye(physics.dim).map(r=>r.map(v=>v*0.02));this.x[1]=bias;}
  update(y,u,dt,noise){
    const m=this.model,n=m.dim;
    if(this.mode==='full_state'){this.x=[...y];return;}
    if(this.kind==='luenberger'){
      const innovation=y.map((v,i)=>v-mv(m.C,this.x)[i]);
      const dx=mv(m.A,this.x).map((v,i)=>v+m.B[i][0]*u+mv(m.L,innovation)[i]);
      this.x=this.x.map((v,i)=>v+dt*dx[i]);return;
    }
    let C=m.C.map(r=>[...r]),F=eye(n);
    if(this.kind==='ekf'){
      const eps=1e-5;this.x=m.step(this.x,u,dt);
      for(let j=0;j<n;j++){
        const a=[...this.x],b=[...this.x];a[j]+=eps;b[j]-=eps;const fa=m.rhs(a,u),fb=m.rhs(b,u);
        for(let i=0;i<n;i++)F[i][j]+=dt*(fa[i]-fb[i])/(2*eps);
      }
      if(this.mode==='cart_and_tip')for(let i=0;i<m.n;i++)C[1][i+1]=m.lengths[i]*Math.cos(this.x[i+1]);
    }else{
      this.x=this.x.map((v,i)=>v+dt*(mv(m.A,this.x)[i]+m.B[i][0]*u));
      F=F.map((r,i)=>r.map((v,j)=>v+dt*m.A[i][j]));
    }
    const predicted=this.kind==='ekf'?m.measure(this.x,this.mode):mv(C,this.x), innov=y.map((v,i)=>v-predicted[i]);
    const P=mm(mm(F,this.P),tr(F));for(let i=0;i<n;i++)P[i][i]+=dt*0.01;
    const CP=mm(C,P),S=mm(CP,tr(C)),rn=Math.max(noise*noise,1e-8);for(let i=0;i<S.length;i++)S[i][i]+=rn;
    const gain=tr(tr(CP).map(r=>solve(S,r))), G=tr(gain);
    this.x=this.x.map((v,i)=>v+G[i].reduce((s,g,j)=>s+g*innov[j],0));
    const J=eye(n),GC=mm(G,C);for(let i=0;i<n;i++)for(let j=0;j<n;j++)J[i][j]-=GC[i][j];
    this.P=add(mm(mm(J,P),tr(J)),mm(G,tr(G)).map(r=>r.map(v=>v*rn)));
    this.P=this.P.map((r,i)=>r.map((v,j)=>(v+this.P[j][i])/2));
  }
}
