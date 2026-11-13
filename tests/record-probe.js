window.__recordProbe={results:[]};
(async()=>{
  for(const [width,height,attach,cpu,mime] of [[640,360,false,false,'video/webm;codecs=vp8'],[640,361,false,false,'video/webm;codecs=vp8'],[1920,1080,false,false,'video/webm;codecs=vp8'],[640,360,true,false,'video/webm;codecs=vp8'],[640,360,false,true,'video/webm;codecs=vp8'],[640,360,false,false,'video/webm;codecs=vp9']]){
    const c=document.createElement('canvas');c.width=width;c.height=height;
    if(attach){c.style='position:fixed;left:0;top:0;width:200px;height:120px;z-index:9999';document.body.append(c);}
    const ctx=c.getContext('2d',{willReadFrequently:cpu}),stream=c.captureStream(30),chunks=[],events=[];
    const rec=new MediaRecorder(stream,{mimeType:mime});
    rec.ondataavailable=e=>{events.push(e.data.size);chunks.push(e.data)};
    rec.onerror=e=>events.push(String(e.error));
    const done=new Promise(resolve=>rec.onstop=resolve);rec.start(250);
    for(let i=0;i<8;i++){ctx.fillStyle=i%2?'red':'blue';ctx.fillRect(0,0,width,height);stream.getVideoTracks()[0].requestFrame?.();await new Promise(r=>setTimeout(r,150));}
    rec.stop();await done;
    window.__recordProbe.results.push({width,height,attach,cpu,mime,events,size:new Blob(chunks).size,track:stream.getVideoTracks()[0].readyState});
    stream.getTracks().forEach(t=>t.stop());c.remove();
  }
  window.__recordProbe.done=true;
})().catch(e=>{window.__recordProbe.error=String(e);window.__recordProbe.done=true;});
