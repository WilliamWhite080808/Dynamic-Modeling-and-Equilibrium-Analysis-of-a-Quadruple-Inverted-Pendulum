"""Two independent complete distributions: system browser and native window."""
from pathlib import Path
import argparse,copy,datetime,hashlib,json,os,shutil,struct,subprocess,zipfile,zlib
from .build_folder import export
from .motion_text import dumps

ROOT=Path(__file__).resolve().parent.parent

def linked_copy(source,destination):
    try:os.link(source,destination)
    except OSError:shutil.copy2(source,destination)

def compile_app(source,target,references=()):
    compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    args=[str(compiler),'/nologo','/codepage:65001','/target:winexe','/platform:x64','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll','/out:'+str(Path(target).resolve())]
    args.extend('/reference:'+str(Path(p).resolve()) for p in references)
    args.append(source);subprocess.run(args,cwd=ROOT/'cluster',check=True)

def make(destination,edition,seed,lightweight=False):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    if (destination/'release.toml').exists():raise ValueError('不要覆盖已经发布的版本')
    shutil.copytree(Path(seed)/'runtime',destination/'runtime',copy_function=linked_copy,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.nbc','*.nbi'))
    shutil.copytree(ROOT/'triple_pendulum',destination/'triple_pendulum',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.nbc','*.nbi'))
    shutil.copytree(ROOT/'web',destination/'web');shutil.copy2(ROOT/'launch.py',destination/'launch.py')
    source=ROOT/'docs/motion-plugin-format.md'
    if source.exists():(destination/'轨迹格式说明.md').write_text(source.read_text(encoding='utf8').split('\n---\n',1)[0]+'\n',encoding='utf8')
    (destination/'组件来源.txt').write_text('Python 与科学计算库来自官方发行和 PyPI，许可证保留在 runtime 内。\n桌面版使用 Microsoft WebView2 Fixed Version 157.0.4341.57 及 SDK 1.0.2903.40，官方说明：https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution\n',encoding='utf8')
    (destination/'results').mkdir(exist_ok=True)
    entry='打开网页版.exe' if edition=='web' else '倒立摆.exe'
    (destination/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>倒立摆实验室</title><body style="font:20px system-ui;padding:48px">请先双击同目录的“'+entry+'”。启动后，此 HTML 会自动直达仿真。</body></html>',encoding='utf8')
    if edition=='web':compile_app('WebLauncher.cs',destination/'打开网页版.exe')
    else:
        sdk=ROOT/'results/desktop-build/sdk';net=sdk/'lib/net462'
        for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll'):shutil.copy2(net/name,destination/name)
        shutil.copy2(sdk/'runtimes/win-x64/native/WebView2Loader.dll',destination/'WebView2Loader.dll')
        licenses=destination/'许可';licenses.mkdir(exist_ok=True)
        for name in ('LICENSE.txt','NOTICE.txt'):shutil.copy2(sdk/name,licenses/('WebView2-'+name))
        if not lightweight:
            engine=next((ROOT/'results/desktop-build/fixed-runtime').glob('*'))
            shutil.copytree(engine,destination/'engine',copy_function=linked_copy)
        compile_app('DesktopHost.cs',destination/'倒立摆.exe',[net/'Microsoft.Web.WebView2.Core.dll',net/'Microsoft.Web.WebView2.WinForms.dll'])
    return destination

def sync_data(web,desktop,lightweight=False):
    report=export(web,compact=lightweight)
    for name in ('motions','models'):shutil.copytree(Path(web)/name,Path(desktop)/name,dirs_exist_ok=True)
    expected={p.name for p in (Path(web)/'motions').glob('*.toml')}
    for path in (Path(desktop)/'motions').glob('*.toml'):
        if path.name not in expected:path.unlink()
    from . import transitions
    computed=report['orders'].get(5,0)+report['unpaired_directions_not_published']
    report.update(built_at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),fifth_computed_total=computed,trajectory_format='TOML v2; lossless Hermite nodes',requires_external_python=False,requires_network=False,one_click_start=True,stable_hold_seconds=5,layout='阶数在上；仿真及图表居中；起点终点在下')
    if lightweight:report['trajectory_format']='TOML v3; lossless IEEE754 state-Hermite coefficients'
    for folder,kind in ((Path(web),'网页版'),(Path(desktop),'桌面版')):
        value=dict(report,edition=kind,entry='打开网页版.exe' if kind=='网页版' else '倒立摆.exe',browser_engine='installed browser with verified executable fallback' if kind=='网页版' else 'bundled Microsoft WebView2 Fixed Version 157.0.4341.57')
        (folder/'release.toml').write_text(dumps(value),encoding='utf8')
        notes=[kind+' · 倒立摆实验室','完整解压后，双击“'+value['entry']+'”，自动直接进入仿真，无选择页。',
            '自动检测实际可用浏览器，支持 Firefox/Chrome/Edge 等，不依赖默认 Edge 关联。首次使用 EXE 启动服务后，index.html 可直接进入。' if kind=='网页版' else '独立桌面窗口，自带浏览器引擎，不依赖系统 Edge、Firefox 或 Chrome。',
            '无需安装 Python、Node.js 或求解器；支持 Windows 10/11 64 位。启动窗口显示状态，首次校验轨迹；失败显示具体错误并写入 results 日志。',
            '完整功能：自定义初值求解、参数、仓库、图表、变速、时间轴、扰动、核心区域录制及数据导出。',
            '阶数在最上方，起点和终点在仿真/图表下方；切换即执行，稳定保持 5 个仿真秒后循环。',
            f'前四阶完整 310 条方向，五阶 {report["orders"].get(5,0)} 条已独立双向配对的方向。累计已解但未配对方向没有伪造为逆解；未全部验收前不开放五阶完整序列。',
            '新初值可求解和保存成功记录，不保证任意初值均有可行解。摆杆完全被动，仅小车牵引；默认轨道 ±2.4 m、牵引力 120 N、变化率 500 N/s。',
            'motions 为固定插件目录，命名“阶数_姿态A_姿态B.toml”。[ab]/[ba] 各自独立真实解；q/v/a/u/K 是分段 Hermite 参考及反馈参数，每个矩阵节点单独一行。能推导的间隔及默认初值不重复写。',
            'models/standard.toml 为共用模型。首次建立 .cache 索引，之后新增/修改插件仅经“检查轨迹更新”手动激活，坏文件保留旧快照。阶数从有效数据发现。',
            'trajectory_repository 保存新实验成功记录，recordings 保存录制，results 保存日志。升级时保留自己的记录。',
            '整体转发此文件夹或对应 ZIP，即可复刻完整功能；不要只取 EXE/HTML，也不要从压缩软件预览启动。']
        (folder/'使用说明.txt').write_text('\n\n'.join(notes)+'\n',encoding='utf-8-sig')
    return report

def prepare_cache(folder):
    from .motion_plugins import MotionStore
    folder=Path(folder)
    if (folder/'.cache/instance.json').exists():raise ValueError('只能预载新构建目录，不能自动更新已运行应用')
    existing=(folder/'.cache/trajectory-index.json').exists()
    store=MotionStore(folder)
    if existing:store.refresh()
    return dict(pairs=len(store.value['files']),orders=store.orders())

def zip_edition(folder,target):
    folder=Path(folder);target=Path(target)
    index=folder/'.cache/trajectory-index.json'
    seeded=json.loads(index.read_bytes()).get('source_preload',False) if index.exists() else False
    previous=zipfile.ZipFile(target) if target.exists() else None
    temporary=target.with_name(target.name+'.new')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(folder.rglob('*')):
            parts=path.relative_to(folder).parts
            preload=parts==('.cache','trajectory-index.json') or (not seeded and parts[:2]==('.cache','motions') and path.name.endswith('.json.gz'))
            regular=not any(p in ('.cache','__pycache__','recordings','trajectory_repository') for p in parts)
            if path.is_file() and (regular or preload) and not (parts[0]=='results' and path.suffix=='.log'):
                name=(Path(folder.name)/path.relative_to(folder)).as_posix();old=previous.NameToInfo.get(name) if previous else None
                same=old and old.file_size==path.stat().st_size and not old.flag_bits&9
                if same:
                    crc=0
                    with path.open('rb') as source:
                        for chunk in iter(lambda:source.read(1024*1024),b''):crc=zlib.crc32(chunk,crc)
                    same=crc==old.CRC
                if same:
                    previous.fp.seek(old.header_offset);header=previous.fp.read(30)
                    if header[:4]!=b'PK\x03\x04':raise ValueError('旧 ZIP 文件头损坏')
                    namesize,extrasize=struct.unpack_from('<HH',header,26)
                    item=copy.copy(old);item.header_offset=bundle.fp.tell();bundle.fp.write(header)
                    remaining=namesize+extrasize+old.compress_size
                    while remaining:
                        chunk=previous.fp.read(min(1024*1024,remaining))
                        if not chunk:raise ValueError('旧 ZIP 数据截断')
                        bundle.fp.write(chunk);remaining-=len(chunk)
                    bundle.filelist.append(item);bundle.NameToInfo[name]=item;bundle.start_dir=bundle.fp.tell();bundle._didModify=True
                else:bundle.write(path,arcname=name,compress_type=zipfile.ZIP_STORED if preload else zipfile.ZIP_DEFLATED)
    if previous:previous.close()
    with zipfile.ZipFile(temporary) as checked:
        broken=checked.testzip()
        if broken:raise ValueError('ZIP 校验失败：'+broken)
    temporary.replace(target)
    return dict(file=str(target),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination');p.add_argument('--seed',required=True);args=p.parse_args();dest=Path(args.destination)
    web=make(dest/'网页版','web',args.seed);desktop=make(dest/'桌面版','desktop',args.seed);report=sync_data(web,desktop)
    prepare_cache(web);prepare_cache(desktop)
    print(json.dumps(report,ensure_ascii=False),flush=True)
