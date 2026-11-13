"""Create a full folder distribution from a fixed, certified bank snapshot."""
from pathlib import Path
import datetime,hashlib,json,shutil,zipfile,subprocess
from . import transitions,motion_plugins
from .motion_text import dumps as toml,motion_bytes

ROOT=Path(__file__).resolve().parent.parent

def export(destination):
    destination=Path(destination);motions=destination/'motions';models=destination/'models';motions.mkdir(parents=True,exist_ok=True);models.mkdir(exist_ok=True)
    rows=transitions.statuses();ready={k:r for k,r in rows.items() if r['status']=='ready'};pairs=[];signatures={};counts={};omitted=0
    # Read immutable admitted bytes once: background calculation may continue.
    for key,row in sorted(ready.items()):
        n,a,b=row['order'],row['source'],row['target']
        reverse=ready.get(transitions.key(n,b,a))
        if reverse is None:omitted+=1;continue
        if a>b:continue
        directions=[]
        for r in (row,reverse):
            raw=(transitions.ROOT/r['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=r['sha256']:raise ValueError('源文件摘要不符')
            plan=json.loads(raw)
            if plan.get('segments') or plan.get('route_waypoints'):raise ValueError('不导出中间稳态拼接路径')
            data=motion_plugins.pack(plan);data['origin_sha256']=r['sha256'];directions.append(data)
            signatures.setdefault(n,[]).append(f'{r["source"]}-{r["target"]}:{data["runtime_sha256"]}')
        pairs.append(dict(n=n,ends=[a,b],ab=directions[0],ba=directions[1]))
        counts[n]=counts.get(n,0)+2
    sequence={}
    legacy=transitions.catalog()
    for n,entries in signatures.items():
        if counts[n]==2**n*(2**n-1) and legacy['cruise_ready'].get(n):sequence[str(n)]=hashlib.sha256('\n'.join(sorted(entries)).encode()).hexdigest()
    params={k:v for k,v in ready[next(iter(ready))]['parameters'].items() if k!='n'}
    model=dict(v=1,parameters=params,units='SI; absolute angles measured from vertical up',force_rate=500,actuators='cart only; passive viscous joints',sequence_signatures=sequence)
    (models/'standard.toml').write_text(toml(model),encoding='utf8')
    expected_files=set()
    for pair in pairs:
        doc=dict(v=1,basis='state-hermite-v1',model_sha256=motion_plugins.model_digest(model),**pair)
        raw=motion_bytes(doc);path=motions/f'{pair["n"]}_{pair["ends"][0]}_{pair["ends"][1]}.toml';expected_files.add(path.name)
        if path.exists() and path.read_bytes()==raw:continue
        motion_plugins.MotionStore.validate(None,raw,model);path.write_bytes(raw)
    for path in motions.glob('*.toml'):
        if path.name not in expected_files:path.unlink()
    return dict(orders=counts,pairs=len(pairs),directions=sum(counts.values()),unpaired_directions_not_published=omitted,sequence_ready=sorted(map(int,sequence)))

def build(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    if (destination/'release.json').exists():raise ValueError('请使用新的版本目录，保留已有分发和用户记录')
    cache=ROOT/'results/runtime-build';runtime=destination/'runtime';runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(cache/'python-3.11.9-embed-amd64.zip') as bundle:bundle.extractall(runtime)
    site=runtime/'Lib/site-packages';site.mkdir(parents=True,exist_ok=True)
    versions=[]
    for wheel in sorted((cache/'wheels').glob('*.whl')):
        with zipfile.ZipFile(wheel) as bundle:
            for entry in bundle.infolist():
                name=entry.filename
                if '.data/' in name:
                    group,_,tail=name.partition('.data/')
                    if tail.startswith(('purelib/','platlib/')):name=tail.split('/',1)[1]
                    else:continue
                parts=Path(name).parts
                if any(p in ('tests','test','__pycache__') for p in parts) or name.endswith(('.pyc','.pyo')):continue
                target=site/name
                if not target.resolve().is_relative_to(site.resolve()):raise ValueError('Unsafe wheel member')
                if entry.is_dir():target.mkdir(parents=True,exist_ok=True)
                else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bundle.read(entry))
        versions.append(dict(wheel=wheel.name,sha256=hashlib.sha256(wheel.read_bytes()).hexdigest()))
    # _pth isolates all imports from registry, PYTHONPATH and user site-packages.
    (runtime/'python311._pth').write_text('python311.zip\n.\nLib/site-packages\n..\nimport site\n',encoding='utf8')
    for name in ('msvcp140.dll','vcomp140.dll'):
        source=Path('C:/Windows/System32')/name
        if source.exists():shutil.copy2(source,runtime/name)
    # Static libraries/headers are build-time assets; the solver uses DLLs.
    casadi=site/'casadi'
    for path in casadi.rglob('*'):
        if path.is_file() and path.name.endswith(('.lib','.dll.a')):path.unlink()
    for name in ('include','cmake'):
        path=casadi/name
        if path.is_dir():shutil.rmtree(path)
    shutil.copytree(ROOT/'triple_pendulum',destination/'triple_pendulum',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.nbc','*.nbi'))
    shutil.copytree(ROOT/'web',destination/'web')
    for name in ('launch.py','启动实验室.cmd','index.html'):shutil.copy2(ROOT/name,destination/name)
    compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    if compiler.exists():
        target=(cache/'LabLauncher.exe').resolve()
        subprocess.run([str(compiler),'/nologo','/target:winexe','/reference:System.Windows.Forms.dll','/out:'+str(target),'FolderLauncher.cs'],cwd=ROOT/'cluster',check=True)
        shutil.copy2(target,destination/'倒立摆实验室.exe')
    (destination/'results').mkdir(exist_ok=True)
    for name in ('fourth-order-worker-audit.json','equilibrium-worker-audit.json'):
        if (ROOT/'results'/name).exists():shutil.copy2(ROOT/'results'/name,destination/'results'/name)
    report=export(destination)
    report.update(built_at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),runtime='CPython 3.11.9 Windows x64 embedded',wheels=versions,complete_solver=True,requires_external_python=False,requires_network=False,activation='first launch builds cache; subsequent changes require manual check')
    (destination/'release.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (destination/'使用说明.txt').write_text('''倒立摆实验室 · 完整便携文件夹（Windows 10/11 64 位）

请先解压整个文件夹，然后双击“倒立摆实验室.exe”（或“启动实验室.cmd”）。自动进入仿真，没有入口选择页。
无需安装 Python、求解器或 Node.js，无需联网。系统自带的 Edge/Chrome/Firefox 用作界面。
启动后 index.html 会直接进入这个文件夹的实验室。HTML 受浏览器权限限制，不能自行启动本机进程；第一次请双击上面的启动入口。

完整功能：自定义初值求解、参数调整、稳态切换、仓库、实时物理积分、图表、调速、拖动时间轴、核心区域录制和数据导出。新初值求解耗时取决于机器与难度，不能保证任意初值成功。
前四阶全部 310 条有向转换；五阶仅包含 release.json 里列出的已验收双向配对，未完成方向显示为不可用，不宣称五阶全量完成。

motions 是固定插件目录，一对姿态一个 .motion.json，ab/ba 各自为独立真实解。表示方式为分段三次 Hermite 控制参考，非视频，未更改已验收控制轨迹的任何数值。
models 为共用物理模型。.cache 是可再生成的激活快照。首次运行建立索引，以后复制/修改插件不会自动生效，必须点击“检查轨迹更新”。
阶数按钮从有效插件生成，可扩展六阶及更多；不要用未验收数据或缺失系数的草案文件。
trajectory_repository 存新实验成功记录，recordings 存核心区录制，results 存启动/错误日志；它们都在本文件夹内。升级时保留自己的记录。

整个文件夹一起转发。请勿只取 HTML，也勿在压缩软件预览中直接启动。
''',encoding='utf-8-sig')
    print(json.dumps(dict(path=str(destination),**{k:report[k] for k in ('orders','pairs','directions','unpaired_directions_not_published')}),ensure_ascii=False),flush=True)
    return report

def archive(destination):
    destination=Path(destination);target=destination.with_suffix('.zip')
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(destination.rglob('*')):
            parts=path.relative_to(destination).parts
            if path.is_file() and not any(p in ('.cache','__pycache__','recordings','trajectory_repository') for p in parts) and path.name not in ('server.log','startup-error.txt'):bundle.write(path,arcname=str(Path(destination.name)/path.relative_to(destination)))
    print(json.dumps(dict(zip=str(target),MiB=target.stat().st_size/1048576),ensure_ascii=False),flush=True)
    return target

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('destination');parser.add_argument('--zip',action='store_true');args=parser.parse_args()
    build(args.destination)
    if args.zip:archive(args.destination)
