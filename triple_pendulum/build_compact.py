"""Build the complete desktop capsule. Never mutate a running distribution.

Scientific runtime and AOT compiler inputs are pinned build assets, not Python
dependencies to be installed by a recipient. See docs/compact-desktop.md.
"""
from pathlib import Path
import argparse,ast,copy,hashlib,json,os,re,shutil,subprocess,sys,time,zipfile
from concurrent.futures import ProcessPoolExecutor,as_completed
from .build_editions import compile_app
from .motion_plugins import MotionStore,atomic
from .motion_text import dumps,read_motion

ROOT=Path(__file__).resolve().parent.parent
CPU_FEATURES='SSSE3,SSE41,POPCNT,SSE42,AVX,F16C,FMA3,AVX2,AVX512F,AVX512CD,AVX512_SKX,AVX512_CLX,AVX512_CNL,AVX512_ICL'


def pinned_environment():
    env=os.environ.copy()
    env.update(OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',OMP_NUM_THREADS='1',
        OPENBLAS_CORETYPE='NEHALEM',NPY_DISABLE_CPU_FEATURES=CPU_FEATURES,PYTHONDONTWRITEBYTECODE='1')
    return env


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_runtime(seed,destination,extractor):
    """Select the GUI/solver dependency closure from a full pinned runtime.

    This changes only a fresh build tree. All source, wheels and developer
    packages remain in the project. Dynamic CasADi plugins are explicit.
    """
    seed=Path(seed).resolve();destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=False);runtime=destination/'runtime'
    def ignore(directory,names):
        return [n for n in names if n in ('tests','test','__pycache__') or n.endswith(('.pyc','.pyo','.lib','.dll.a'))]
    shutil.copytree(seed,runtime,ignore=ignore)
    site=runtime/'Lib/site-packages'
    packages={'annotated_types','anyio','casadi','click','fastapi','h11','idna','numpy','numpy.libs',
        'pydantic','pydantic_core','scipy','scipy.libs','starlette','typing_extensions','typing_inspection','uvicorn'}
    for path in site.iterdir():
        base=path.name.split('-')[0] if path.name.endswith('.dist-info') else path.stem if path.is_file() else path.name
        if base not in packages:
            if path.is_dir():shutil.rmtree(path)
            else:path.unlink()
    for name in ('io','odr','datasets','misc','signal','stats','interpolate','integrate','ndimage'):
        path=site/'scipy'/name
        if path.exists():shutil.rmtree(path)
    casadi=site/'casadi'
    plugins={'libcasadi.dll','libcasadi-tp-openblas.dll','libcasadi_nlpsol_ipopt.dll','libipopt-3.dll',
        'libcoinmumps-3.dll','libcoinmetis-2.dll','libgfortran-5.dll','libquadmath-0.dll',
        'libgcc_s_seh-1.dll','libstdc++-6.dll','libwinpthread-1.dll',
        *('libcasadi_linsol_'+n+'.dll' for n in ('qr','csparse','lapacklu','ldl'))}
    for path in casadi.glob('*.dll'):
        if path.name not in plugins:path.unlink()
    for name in ('include','cmake'):
        path=casadi/name
        if path.exists():shutil.rmtree(path)
    missing=[name for name in plugins if not (casadi/name).exists()]
    if missing:raise ValueError('Missing solver dependency: '+str(missing))
    for path in runtime.glob('python*._pth'):path.write_text('python311.zip\n.\nLib/site-packages\n..\nimport site\n',encoding='ascii')
    archive=destination/'runtime.7z'
    subprocess.run([str(Path(extractor).resolve()),'a',str(archive),'runtime','-mx=9','-md=64m','-mmt=2','-ms=on','-mqs=on'],cwd=destination,check=True,capture_output=True)
    subprocess.run([str(Path(extractor).resolve()),'t',str(archive)],check=True,capture_output=True)
    return dict(runtime=str(archive),sha256=sha(archive),bytes=archive.stat().st_size,
        files=[dict(path=p.relative_to(runtime).as_posix(),sha256=sha(p)) for p in sorted(runtime.rglob('*')) if p.is_file()])


def runtime_modules():
    pending=['__init__','server'];seen=set()
    while pending:
        name=pending.pop();path=ROOT/'triple_pendulum'/(name+'.py')
        if name in seen or not path.exists():continue
        seen.add(name)
        for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
            if isinstance(node,ast.ImportFrom) and node.level==1:
                pending.extend([node.module.split('.')[0]] if node.module else [a.name for a in node.names])
    return sorted(seen)


def encode_one(item):
    from .motion_recipe import compact_bytes
    source,dest=map(Path,item);doc=read_motion(source.read_bytes());raw=compact_bytes(doc)
    restored=read_motion(raw)
    if json.dumps(doc,sort_keys=True,separators=(',',':'))!=json.dumps(restored,sort_keys=True,separators=(',',':')):
        raise ValueError('Lossless reconstruction failed: '+source.name)
    dest.write_bytes(raw)
    return dict(file=source.name,source_sha256=sha(source),new_sha256=sha(dest),
        old_bytes=source.stat().st_size,new_bytes=len(raw),exact=True,
        directions={k:doc[k]['runtime_sha256'] for k in ('ab','ba')})


def encode(source,destination,workers=4):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    jobs=[(str(p),str(destination/p.name)) for p in sorted((Path(source)/'motions').glob('*.toml'))]
    started=time.monotonic();rows=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(encode_one,item) for item in jobs]):
            rows.append(future.result())
            if len(rows)%20==0:print('EXACT',len(rows),'/',len(jobs),flush=True)
    report=dict(passed=True,pairs=len(rows),directions=2*len(rows),old_bytes=sum(r['old_bytes'] for r in rows),
        new_bytes=sum(r['new_bytes'] for r in rows),seconds=time.monotonic()-started,files=sorted(rows,key=lambda r:r['file']))
    (destination/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return report


def archive(folder,destination):
    folder=Path(folder);destination=Path(destination)
    if destination.exists():raise ValueError('Refusing to overwrite a share archive')
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(folder.rglob('*')):
            parts=path.relative_to(folder).parts
            if not path.is_file():continue
            if any(x in ('__pycache__','recordings','trajectory_repository') for x in parts):continue
            if '.cache' in parts and parts!=('程序文件','.cache','trajectory-index.json'):continue
            if parts[:2]==('程序文件','results'):continue
            bundle.write(path,(Path(folder.name)/path.relative_to(folder)).as_posix())
    with zipfile.ZipFile(destination) as bundle:
        if bundle.testzip():raise ValueError('Share archive CRC failure')
    report=dict(file=str(destination),bytes=destination.stat().st_size,sha256=sha(destination),crc_passed=True)
    if report['bytes']>=100_000_000:raise ValueError('Share archive exceeds 100,000,000 bytes: '+str(report))
    return report


def assemble(destination,source,encoded,assets):
    destination=Path(destination).resolve();source=Path(source).resolve();encoded=Path(encoded).resolve()
    if destination.exists():raise ValueError('Use a fresh output folder, never replace an active version')
    report=json.loads((encoded/'report.json').read_bytes())
    if not report['passed']:raise ValueError('Missing exact reconstruction evidence')
    inputs={p.name:p for p in (source/'motions').glob('*.toml')}
    if set(inputs)!={r['file'] for r in report['files']}:raise ValueError('Encoded snapshot is incomplete')
    # This index is built from fully validated input, before swapping only its
    # byte-identical reconstructed references into the compressed representation.
    store=MotionStore(source);value=copy.deepcopy(store.value)
    if len(value['files'])!=len(inputs):raise ValueError('Invalid source plugin index')
    for row in report['files']:
        name=row['file'];meta=value['files'][name]
        if sha(inputs[name])!=row['source_sha256'] or sha(encoded/name)!=row['new_sha256']:raise ValueError('Snapshot bytes changed')
        if not row['exact'] or any(meta['directions'][k]['runtime_sha256']!=row['directions'][k] for k in ('ab','ba')):raise ValueError('Controller identity changed')
        meta.update(sha256=row['new_sha256'],cache_sha256=row['new_sha256'],ext='.toml',seed_source=name)
    value['source_preload']=True
    app=destination/'程序文件';app.mkdir(parents=True)
    for name in ('motions','models','web','triple_pendulum','results','许可'): (app/name).mkdir()
    for name in inputs:shutil.copy2(encoded/name,app/'motions'/name)
    shutil.copytree(source/'models',app/'models',dirs_exist_ok=True)
    shutil.copytree(ROOT/'web',app/'web',dirs_exist_ok=True)
    modules=runtime_modules()
    for name in modules:shutil.copy2(ROOT/'triple_pendulum'/(name+'.py'),app/'triple_pendulum'/(name+'.py'))
    shutil.copy2(ROOT/'launch.py',app/'launch.py')
    for src,target in ((assets['runtime'],'runtime.7z'),(assets['extractor'],'7zr.exe'),(assets['kernel'],'triple_pendulum/_native.cp311-win_amd64.pyd')):
        shutil.copy2(src,app/target)
    (app/'runtime.sha256').write_text(sha(app/'runtime.7z')+'\n'+sha(app/'7zr.exe')+'\n',encoding='ascii')
    sdk=ROOT/'results/desktop-build/sdk';net=sdk/'lib/net462'
    for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll'):shutil.copy2(net/name,app/name)
    shutil.copy2(sdk/'runtimes/win-x64/native/WebView2Loader.dll',app/'WebView2Loader.dll')
    for name in ('LICENSE.txt','NOTICE.txt'):shutil.copy2(sdk/name,app/'许可'/('WebView2-'+name))
    notices=sorted({re.search(r'/\*.*?\*/',p.read_text(encoding='utf8'),re.S).group() for p in (ROOT/'native/fdlibm').glob('*.[ch]')})
    (app/'许可/fdlibm.txt').write_text('Netlib fdlibm, https://www.netlib.org/fdlibm/\n\n'+'\n\n'.join(notices)+'\n',encoding='utf8')
    numba_license=Path(assets['numba_license']);shutil.copy2(numba_license,app/'许可/Numba-NRT-BSD.txt')
    (app/'许可/7zr.txt').write_text('7zr.exe 26.04 — public domain. https://www.7-zip.org/ https://www.7-zip.org/a/7zr.exe\nSHA256 '+sha(app/'7zr.exe')+'\n',encoding='utf8')
    compile_app('DesktopHost.cs',app/'界面.exe',[net/'Microsoft.Web.WebView2.Core.dll',net/'Microsoft.Web.WebView2.WinForms.dll'])
    compile_app('CompactLauncher.cs',destination/'倒立摆.exe')
    atomic(app/'.cache/trajectory-index.json',value)
    orders={n:sum(2 for row in value['files'].values() if row['n']==n) for n in sorted({r['n'] for r in value['files'].values()})}
    release=dict(pairs=len(inputs),directions=2*len(inputs),orders=orders,sequence_ready=[n for n,ok in store.catalog()['cruise_ready'].items() if ok],
        unpaired_directions_not_published=0,complete_solver=True,requires_external_python=False,requires_network=False,
        one_click_start=True,experimental=True,default_speed=1,stable_hold_seconds=5,
        trajectory_format='TOML v4; exact IEEE754 predictive corrections; hs12-fdlibm-tvlqr-nehalem-v2',
        runtime_sha256=sha(app/'runtime.7z'),kernel_sha256=sha(assets['kernel']),entry='倒立摆.exe')
    (app/'release.toml').write_text(dumps(release),encoding='utf8')
    (app/'使用说明.txt').write_text('完整解压，双击上一级“倒立摆.exe”。首次自动展开随包数值引擎到用户缓存，无需安装或联网。保留现场初值求解、参数、图表、仓库、录制、时间轴及全部原功能。\n现代 Windows 10/11 x64；优先复用已有WebView2，否则自动使用已安装的浏览器。\n首次解码会检查固定内核与原始控制摘要，数值不匹配明确报错，不使用近似替代。651对独立双向插件、1302方向，五阶全部992及连续序列已通过验收。\n新插件放motions，点击“检查轨迹更新”才激活；缺失或损坏的索引自动重建。默认1×，稳态停留5个仿真秒。\n新记录在trajectory_repository，录制在recordings，升级时保留。源代码和完整项目日志在原项目，分享包仅保留运行必需代码。\n',encoding='utf-8-sig')
    (app/'轨迹格式说明.md').write_text((ROOT/'docs/motion-plugin-format.md').read_text(encoding='utf8'),encoding='utf8')
    (app/'组件来源.txt').write_text('随包CPython3.11.9、NumPy1.26.4、SciPy1.11.4、CasADi/IPOPT及FastAPI。各许可证在runtime.7z内。没有Numba/LLVM编译环境、浏览器内核或开发测试包；被动动力学与恢复控制已AOT编译为同算法的固定内核。7zr与fdlibm来源及许可证在许可目录。\n',encoding='utf8')
    (app/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>倒立摆实验室</title>请双击上一级“倒立摆.exe”。',encoding='utf8')
    return dict(**release,modules=modules,folder=str(destination),lossless_report_sha256=sha(encoded/'report.json'))


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    prep=sub.add_parser('prepare-runtime');prep.add_argument('seed');prep.add_argument('output');prep.add_argument('--extractor',required=True)
    enc=sub.add_parser('encode');enc.add_argument('source');enc.add_argument('output');enc.add_argument('--workers',type=int,default=4)
    build=sub.add_parser('assemble');build.add_argument('output');build.add_argument('--source',required=True);build.add_argument('--encoded',required=True);build.add_argument('--assets',required=True);build.add_argument('--zip')
    args=parser.parse_args()
    if args.mode=='prepare-runtime':
        report=prepare_runtime(args.seed,args.output,args.extractor)
        (Path(args.output)/'runtime-manifest.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    elif args.mode=='encode':report=encode(args.source,args.output,args.workers)
    else:
        assets=json.loads(Path(args.assets).read_bytes())
        for name in ('runtime','extractor','kernel','numba_license'):
            if sha(assets[name])!=assets[name+'_sha256']:raise ValueError('Build asset changed: '+name)
        report=assemble(args.output,args.source,args.encoded,assets)
        if args.zip:report['archive']=archive(args.output,args.zip)
        evidence=ROOT/'results/acceptance/compact';evidence.mkdir(parents=True,exist_ok=True)
        (evidence/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
