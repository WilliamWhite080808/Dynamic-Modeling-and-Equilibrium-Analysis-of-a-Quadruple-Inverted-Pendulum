"""Two independent complete distributions: system browser and native window."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,shutil,subprocess,zipfile
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

def make(destination,edition,seed):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    if (destination/'release.toml').exists():raise ValueError('不要覆盖已经发布的版本')
    shutil.copytree(Path(seed)/'runtime',destination/'runtime',copy_function=linked_copy,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.nbc','*.nbi'))
    shutil.copytree(ROOT/'triple_pendulum',destination/'triple_pendulum',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.nbc','*.nbi'))
    shutil.copytree(ROOT/'web',destination/'web');shutil.copy2(ROOT/'launch.py',destination/'launch.py')
    (destination/'results').mkdir(exist_ok=True)
    entry='打开网页版.exe' if edition=='web' else '倒立摆.exe'
    (destination/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>倒立摆实验室</title><body style="font:20px system-ui;padding:48px">请先双击同目录的“'+entry+'”。启动后，此 HTML 会自动直达仿真。</body></html>',encoding='utf8')
    if edition=='web':compile_app('WebLauncher.cs',destination/'打开网页版.exe')
    else:
        sdk=ROOT/'results/desktop-build/sdk';net=sdk/'lib/net462'
        for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll'):shutil.copy2(net/name,destination/name)
        shutil.copy2(sdk/'runtimes/win-x64/native/WebView2Loader.dll',destination/'WebView2Loader.dll')
        engine=next((ROOT/'results/desktop-build/fixed-runtime').glob('*'))
        shutil.copytree(engine,destination/'engine',copy_function=linked_copy)
        compile_app('DesktopHost.cs',destination/'倒立摆.exe',[net/'Microsoft.Web.WebView2.Core.dll',net/'Microsoft.Web.WebView2.WinForms.dll'])
    return destination

def sync_data(web,desktop):
    report=export(web)
    for name in ('motions','models'):shutil.copytree(Path(web)/name,Path(desktop)/name,dirs_exist_ok=True)
    expected={p.name for p in (Path(web)/'motions').glob('*.toml')}
    for path in (Path(desktop)/'motions').glob('*.toml'):
        if path.name not in expected:path.unlink()
    from . import transitions
    computed=report['orders'].get(5,0)+report['unpaired_directions_not_published']
    report.update(built_at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),fifth_computed_total=computed,trajectory_format='TOML v2; lossless Hermite nodes',requires_external_python=False,requires_network=False)
    for folder,kind in ((Path(web),'网页版'),(Path(desktop),'桌面版')):
        value=dict(report,edition=kind,entry='打开网页版.exe' if kind=='网页版' else '倒立摆.exe',browser_engine='installed browser with verified executable fallback' if kind=='网页版' else 'bundled Microsoft WebView2 Fixed Version 157.0.4341.57')
        (folder/'release.toml').write_text(dumps(value),encoding='utf8')
        notes=[kind+' · 倒立摆实验室','完整解压后，双击“'+value['entry']+'”，自动直接进入仿真，无选择页。',
            '自动检测实际可用浏览器，支持 Firefox/Chrome/Edge 等，不依赖默认 Edge 关联。首次使用 EXE 启动服务后，index.html 可直接进入。' if kind=='网页版' else '独立桌面窗口，自带浏览器引擎，不依赖系统 Edge、Firefox 或 Chrome。',
            '无需安装 Python、Node.js 或求解器；支持 Windows 10/11 64 位。启动窗口显示状态，首次校验轨迹；失败显示具体错误并写入 results 日志。',
            '完整功能：自定义初值求解、参数、仓库、图表、变速、时间轴、扰动、核心区域录制及数据导出。',
            f'前四阶完整 310 条方向，五阶 {report["orders"].get(5,0)} 条已独立双向配对的方向。累计已解但未配对方向没有伪造为逆解；未全部验收前不开放五阶完整序列。',
            '新初值可求解和保存成功记录，不保证任意初值均有可行解。摆杆完全被动，仅小车牵引；默认轨道 ±2.4 m、牵引力 120 N、变化率 500 N/s。',
            'motions 为固定插件目录，命名“阶数_姿态A_姿态B.toml”。[ab]/[ba] 各自独立真实解；q/v/a/u/K 是分段 Hermite 参考及反馈参数，每个矩阵节点单独一行。能推导的间隔及默认初值不重复写。',
            'models/standard.toml 为共用模型。首次建立 .cache 索引，之后新增/修改插件仅经“检查轨迹更新”手动激活，坏文件保留旧快照。阶数从有效数据发现。',
            'trajectory_repository 保存新实验成功记录，recordings 保存录制，results 保存日志。升级时保留自己的记录。',
            '整体转发此文件夹或对应 ZIP，即可复刻完整功能；不要只取 EXE/HTML，也不要从压缩软件预览启动。']
        (folder/'使用说明.txt').write_text('\n\n'.join(notes)+'\n',encoding='utf-8-sig')
    return report

def zip_edition(folder,target):
    folder=Path(folder);target=Path(target)
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(folder.rglob('*')):
            parts=path.relative_to(folder).parts
            if path.is_file() and not any(p in ('.cache','__pycache__','recordings','trajectory_repository') for p in parts) and not (parts[0]=='results' and path.suffix=='.log'):
                bundle.write(path,arcname=str(Path(folder.name)/path.relative_to(folder)))
    return dict(file=str(target),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination');p.add_argument('--seed',required=True);args=p.parse_args();dest=Path(args.destination)
    web=make(dest/'网页版','web',args.seed);desktop=make(dest/'桌面版','desktop',args.seed);report=sync_data(web,desktop)
    print(json.dumps(report,ensure_ascii=False),flush=True)
