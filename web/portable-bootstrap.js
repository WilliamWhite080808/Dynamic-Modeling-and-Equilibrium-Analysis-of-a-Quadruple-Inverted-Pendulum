// Single-file distribution. All data and modules originate inside this HTML.
(async()=>{
  const fail=message=>{const box=document.getElementById('portable-start');box.innerHTML='<h2>无法启动离线实验室</h2><p></p>';box.querySelector('p').textContent=message;};
  try{
    if(!globalThis.DecompressionStream||!globalThis.Worker||!globalThis.crypto?.subtle)throw Error('请使用较新版本的 Edge、Chrome 或 Firefox，先把 HTML 保存到电脑，再用浏览器直接打开。');
    const bundle=JSON.parse(document.getElementById('portable-data').textContent);
    const decode=async text=>{
      const raw=atob(text),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
      return new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());
    };
    const designs=JSON.parse(new TextDecoder().decode(await decode(bundle.designs)));
    const rows=bundle.catalog,cache=new Map(),pending=new Map();
    const idFor=row=>`${row.order}-${row.source}-${row.target}`;
    async function loadPlan(order,source,target){
      const key=`${order}-${source}-${target}`;if(cache.has(key)){const plan=cache.get(key);cache.delete(key);cache.set(key,plan);return plan;}
      if(pending.has(key))return pending.get(key);
      const loading=(async()=>{
        const row=rows.find(row=>idFor(row)===key);if(!row||!bundle.plans[key])throw Error('展示包没有这条路径。');
        const bytes=await decode(bundle.plans[key]);
        const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
        if(digest!==row.sha256)throw Error('内置路径校验失败，请重新解压原始分享包。');
        const plan=JSON.parse(new TextDecoder().decode(bytes));cache.set(key,plan);
        if(cache.size>8)cache.delete(cache.keys().next().value);return plan;
      })();pending.set(key,loading);
      try{return await loading;}finally{pending.delete(key);}
    }
    const result=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json;charset=utf-8'}});
    const compatible=(a,b)=>Object.entries(a).every(([key,value])=>b[key]===value);
    const chooseDesign=(parameters,code,sensor='full_state')=>{
      const design=designs[`${parameters.n}-${code}-${sensor}`];if(!design||!compatible(parameters,design.parameters))throw Error('离线展示包固定使用已验收的默认物理参数。');return structuredClone(design);
    };
    const hanging=rows.filter(row=>row.source==='D'.repeat(row.order)).map(row=>({...row,pattern:row.target}));
    const countCatalog=(entries,extra={})=>({total:entries.length,ready:entries.length,entries,...extra});
    const warehouse=rows.map((row,index)=>({id:String(index+1).padStart(24,'0'),order:row.order,initial:[0,...[...row.source].map(c=>c==='U'?0:Math.PI),...Array(row.order+1).fill(0)],parameters:row.parameters,pattern:row.target,target_label:row.target,settled_at:row.verification.settled_at,duration:row.duration,peak_force:row.verification.max_force,max_cart:row.verification.max_cart,final_error_deg:row.verification.final_angle_deg,status:'verified',has_control_plan:true,created_at:bundle.built_at,title:'已验收的直接转换',source_pose:row.source}));
    globalThis.fetch=async(input,init={})=>{
      const url=new URL(typeof input==='string'?input:input.url,'https://offline.invalid/'),path=url.pathname;
      const body=typeof init.body==='string'?JSON.parse(init.body):{},order=Number(url.searchParams.get('order'));
      try{
        if(path==='/api/health')return result({status:'ok',orders:[1,2,3,4],offline:true});
        if(path==='/api/transitions')return result(countCatalog(order?rows.filter(r=>r.order===order):rows,{force_rate:500,cruise_ready:{1:true,2:true,3:true,4:true},remote_compute:{phase:'complete',jobs:[]},remote_computes:{4:{phase:'complete',jobs:[]}}}));
        if(path==='/api/precomputed')return result(countCatalog(order?hanging.filter(r=>r.order===order):hanging));
        if(path==='/api/design'){
          const design=chooseDesign(body.parameters,body.pattern,body.sensor);
          const base='D'.repeat(body.parameters.n),initial=body.initial;
          const down=initial&&Math.abs(initial[0])<1e-10&&initial.slice(body.parameters.n+1).every(v=>Math.abs(v)<1e-10)&&initial.slice(1,body.parameters.n+1).every(v=>Math.abs(Math.atan2(Math.sin(v-Math.PI),Math.cos(v-Math.PI)))<1e-10);
          design.hanging_plan=down&&body.pattern!==base?await loadPlan(body.parameters.n,base,body.pattern):null;
          design.precomputed_catalog=countCatalog(hanging.filter(r=>r.order===body.parameters.n));return result(design);
        }
        if(path==='/api/transition')return result({plan:await loadPlan(body.parameters.n,body.source,body.target),design:chooseDesign(body.parameters,body.target)});
        if(path==='/api/repository'){
          const solutions=warehouse.filter(row=>row.order===order&&(!url.searchParams.get('pattern')||row.pattern===url.searchParams.get('pattern')));
          return result({solutions,coverage:Object.fromEntries([...new Set(solutions.map(r=>r.pattern))].map(code=>[code,solutions.filter(r=>r.pattern===code).length])),directory:'内置已验收路径'});
        }
        if(path==='/api/repository/record')return result({status:'recorded',storage:'browser'});
        if(path==='/api/recordings')return result({detail:'录制由浏览器直接保存。'},501);
        if(path.startsWith('/api/plan'))return result({detail:'展示包不包含任意新初值优化器。请重新选择起终点，或点击“重新起摆”。'},422);
        return result({detail:'离线展示包没有此接口。'},404);
      }catch(error){return result({detail:error.message},422);}
    };
    const urls={};
    function compile(name){
      if(urls[name])return urls[name];let source=bundle.modules[name];if(typeof source!=='string')throw Error('缺少内置模块：'+name);
      source=source.replace(/from\s*(['"])(\.\/[^'"]+)\1/g,(_,quote,path)=>`from ${quote}${compile(path.slice(2))}${quote}`);
      const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));urls[name]=url;return url;
    }
    globalThis.PENDULUM_OFFLINE={workerUrl:compile('sim-worker.js'),loadPlan,manifest:bundle.manifest};
    for(const id of ['edit-initial','inventory-new','random','near','force','length','rail','dt','duration','apply-physics','sensor','noise']){
      const control=document.getElementById(id);if(control){control.disabled=true;control.title='离线展示包使用已验收的默认初值与物理参数。';}
    }
    document.getElementById('retry').checked=false;document.getElementById('retry').disabled=true;
    document.querySelector('.brand').href=location.href.split('?')[0];
    await import(compile('app.js'));
    document.getElementById('portable-start').remove();
  }catch(error){fail(error.message);console.error(error);}
})();
