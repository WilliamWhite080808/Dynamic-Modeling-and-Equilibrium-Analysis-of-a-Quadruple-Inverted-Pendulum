"""Build an offline, single-HTML 1..4 showcase from certified immutable files."""
import os
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
from pathlib import Path
import base64,gzip,hashlib,json,re,zipfile,datetime
from . import transitions,repository
from .model import Plant,Parameters
from .control import analyze

PROJECT=Path(__file__).resolve().parent.parent
DESTINATION=PROJECT/'dist/前四阶倒立摆_离线分享包'

def compressed(data):return base64.b64encode(gzip.compress(data,compresslevel=9,mtime=0)).decode('ascii')

def app_source():
    source=(PROJECT/'web/app.js').read_text(encoding='utf8')
    source=source.replace("new Worker('/sim-worker.js?v=experiment-4'",'new Worker(globalThis.PENDULUM_OFFLINE.workerUrl')
    source=source.replace('requestedOrder<=5','requestedOrder<=4').replace('order<=5','order<=4').replace('n<=5','n<=4').replace('n>5','n>4')
    begin=source.index('function warehousePresets(order){');end=source.index('async function refreshInventoryCount()',begin)
    source=source[:begin]+'function warehousePresets(){return [];}\n'+source[end:]
    begin=source.index("$('inventory-play').onclick=async()=>{");end=source.index('function updateBankStatus()',begin)
    source=source[:begin]+'''$('inventory-play').onclick=async()=>{
  if(!selectedCard)return;
  const card=selectedCard,source=equilibriumCardCode(card),destination=selectedTarget;
  if(!source)return;
  $('inventory-dialog').close();n=card.order;Object.assign(parameters,card.parameters);
  goalOptions(n,source);await initialize('custom',[...card.initial]);
  if(source!==destination)await playTransfer(source,destination);
};
'''+source[end:]
    source=source.replace("if(e.code==='KeyR')initialize('random');","if(e.code==='KeyR')$('reset').click();")
    source=source.replace("'无法连接本机求解服务，请通过 python -m triple_pendulum.server 启动。'","'内置数据加载失败，请使用新版浏览器重新打开原始 HTML。'")
    source=source.replace("'该参数下的路径尚未就绪。可在参数设置中恢复默认参数后切换。'","'内置路径尚未就绪，请重新打开原始 HTML。'")
    source=source.replace('尚未保存这个自定义初值与目标的路径。求解通过真实积分校验后，会自动记录到仓库。','请选择一张初态卡片，再选择目标；所有不同稳态之间的直接路径均已内置。')
    source=source.replace(":'待求解'",":'选择初态'")
    # Preserve API capture semantics, but report local browser storage honestly.
    source=source.replace('已进入初态仓库','已保存在本机浏览器').replace('本次成功过程已自动保存到初态仓库','本次成功过程已保存在本机浏览器')
    return source

def build():
    DESTINATION.mkdir(parents=True,exist_ok=True)
    rows=[];plans={};designs={};manifest=[]
    for order in range(1,5):
        bank=transitions.catalog(order);assert bank['ready']==2**order*(2**order-1) and bank['cruise_ready'][order]
        for row in bank['entries']:
            assert not row.get('route_waypoints')
            data=(transitions.ROOT/row['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==row['sha256']
            plan=json.loads(data);assert not plan.get('segments')
            key=transitions.key(order,row['source'],row['target']);plans[key]=compressed(data)
            rows.append({key:row[key] for key in ('order','source','target','status','sha256','parameters','duration','verification')})
            manifest.append(dict(key=key,sha256=row['sha256'],duration=row['duration']))
        plant=Plant(Parameters(n=order))
        for code in transitions.patterns(order):
            for sensor in ('full_state','angles_only','cart_and_tip','cart_only'):
                designs[f'{order}-{code}-{sensor}']=analyze(plant,sensor,target=repository.angles(code))
    modules={path.name:path.read_text(encoding='utf8') for path in (PROJECT/'web').glob('*.js') if path.name not in ('portable-bootstrap.js',)}
    modules['app.js']=app_source()
    modules['transfers.js']=modules['transfers.js'].replace('order>5','order>4')
    # UI-only preview uses the same foreground rod ordering as the main renderer.
    # The physical plant/controller modules are copied without modification.
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    payload=dict(built_at=stamp,catalog=rows,plans=plans,designs=compressed(json.dumps(designs,separators=(',',':')).encode()),modules=modules,manifest=dict(total=310,orders={1:2,2:12,3:56,4:240},physics='passive uniform rods; cart force only',force_limit=120,force_rate_limit=500,rail_half_width=2.4,files=manifest,fourth_order_bank_sha256=transitions.bank_signature()))
    html=(PROJECT/'web/index.html').read_text(encoding='utf8')
    html=html.replace('<title>Pendulum Lab · 多重摆实验室</title>','<title>前四阶倒立摆 · 离线实验室</title>')
    html=re.sub(r'<link rel="stylesheet"[^>]+>',lambda _: '<style>'+(PROJECT/'web/lab.css').read_text(encoding='utf8')+'\n.portable-banner{margin:0 0 18px;padding:11px 15px;border:1px solid #d9e6fa;border-radius:9px;background:#edf4ff;color:#5579ac;font-size:11px;line-height:1.8}.portable-banner b{color:#315e9b}#portable-start{position:fixed;inset:0;background:#f4f6faf5;z-index:100;display:grid;place-content:center;text-align:center;gap:14px;color:#42628c;padding:25px}#portable-start p{line-height:1.8}#edit-initial,#inventory-new,#random,#near{display:none}'+ '</style>',html)
    html=html.replace('<button data-order="5">5</button>','')
    html=re.sub(r'<option value="5">五重摆[^<]*</option>','',html)
    html=html.replace('<main class="workspace">','<div id="portable-start"><h2>正在打开离线实验室</h2><p>载入前四阶 310 条已验收路径，无需网络或安装环境。</p></div><main class="workspace"><div class="portable-banner"><b>离线分享版 · 前四阶 310 条直接转换全部内置</b>　选择起点和终点即可运动，稳定保持 10 秒后循环。<br>物理参数固定为已验收默认值；不含任意新初值优化器。施加强扰动失衡后，可点击“重新起摆”。</div>')
    html=html.replace('已有路径可直接轨迹复现；新的组合会通过真实动力学求解，成功后自动入库。','内置全部稳态之间的已验收路径，选定初态与目标后按真实动力学重新积分。')
    html=html.replace('选一张初态卡片，再选择目标平衡姿态。角速度也参与求解。','选择初态卡片与目标稳态，立即执行对应的已验收路径。')
    html=html.replace('改变物理参数后，需要重新求解相应路径。','分享版固定使用已验收参数；新初值与新参数优化需完整求解版。')
    html=html.replace('失衡后自动尝试恢复','任意初值恢复需完整求解版')
    scripts='<script id="portable-data" type="application/json">'+json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')+'</script>\n<script>'+(PROJECT/'web/portable-bootstrap.js').read_text(encoding='utf8')+'</script>'
    html=re.sub(r'<script type="module" src="[^"]+"></script>',lambda _:scripts,html)
    target=DESTINATION/'倒立摆实验室.html';target.write_text(html,encoding='utf8')
    instructions='''前四阶倒立摆 · 离线分享版

解压后，双击“倒立摆实验室.html”，用较新版本 Edge、Chrome 或 Firefox 打开。
无需 Python、Node.js、服务器、集群账号或联网；请先保存文件再打开，不要在聊天软件的文件预览窗口中运行。

包含：单摆 2 条、双摆 12 条、三重摆 56 条、四重摆 240 条，共 310 条已验收直接转换，包含完全下垂基态。
起终点全部展开，可任意切换；稳定 10 秒循环；序列演示、0.1～10 倍调速、真实积分时间轴、六组动态图表、正负 x 扰动、核心区域录制、数据导出和初态路径仓库。
录制结束后由浏览器保存文件；若未自动保存，点击“保存录制文件”。

摆杆为均匀被动刚性杆，关节无驱动，唯一执行器为小车水平力。默认轨道 ±2.4 m，驱动力上限 120 N，变化率上限 500 N/s。
向上姿态由小车反馈控制维持；仿真按真实非线性方程实时积分，不是视频。

展示包固定使用验收默认参数，不含任意新初值/新参数优化器，不含五阶未完成批次。强扰动失衡后请使用“重新起摆”或重新选择起终点。
这是理想刚体模型，不包含杆间碰撞和硬件延迟；不保证任意初值、任意扰动都能恢复。

只转发这个 HTML 即可使用；本说明和验收摘要是可选附件。
'''
    (DESTINATION/'使用说明.txt').write_text(instructions,encoding='utf-8-sig')
    report=dict(built_at=stamp,orders={str(n):dict(poses=2**n,direct_transitions=2**n*(2**n-1),sequence_verified=True) for n in range(1,5)},total_direct_transitions=310,fourth_order_bank_sha256=transitions.bank_signature(),html_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),html_bytes=target.stat().st_size,no_runtime_dependencies=True,external_resources=0,physics_modules_sha256={name:hashlib.sha256(modules[name].encode()).hexdigest() for name in ('physics.js','sim-worker.js','experiment.js')})
    (DESTINATION/'验收摘要.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    archive=DESTINATION.parent/'前四阶倒立摆_离线分享包.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as bundle:
        for file in DESTINATION.iterdir():
            if file.is_file():bundle.write(file,arcname=DESTINATION.name+'/'+file.name)
    print(json.dumps(dict(html=str(target),html_mb=target.stat().st_size/1048576,zip=str(archive),zip_mb=archive.stat().st_size/1048576),ensure_ascii=False))
    return target

if __name__=='__main__':build()
