"""Complete solver editions without bundled browser or duplicated ZIP payload."""
from pathlib import Path
import argparse,json,shutil,datetime
from . import build_editions as editions
from .motion_plugins import MotionStore,atomic
from .motion_text import dumps

def build(destination,seed):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    web=editions.make(destination/'网页版','web',seed,lightweight=True)
    desktop=editions.make(destination/'桌面版','desktop',seed,lightweight=True)
    report=editions.sync_data(web,desktop,lightweight=True)
    for folder,kind in ((web,'网页版'),(desktop,'桌面版')):
        store=MotionStore(folder);store.value['source_preload']=True;atomic(store.index,store.value)
        release=dict(report,edition=kind,entry='打开网页版.exe' if kind=='网页版' else '倒立摆.exe',
            lightweight=True,complete_solver=True,default_speed=1,stable_hold_seconds=5,
            trajectory_format='TOML v3; lossless IEEE754 state-Hermite coefficients',
            browser_engine='existing browser' if kind=='网页版' else 'existing WebView2; existing browser fallback',
            prebuilt_cache='prebuilt metadata; verified byte-copy bootstrap; no coefficient parsing')
        (folder/'release.toml').write_text(dumps(release),encoding='utf8')
        notes=[kind+' · 轻量完整求解版',
            '完整解压后双击 '+release['entry']+'，直接进入仿真，无选择页，无需安装依赖或手动启动服务。',
            '保留自定义初值现场求解、仓库、图表、扰动、时间轴、录制与导出，求解器随包提供。',
            '桌面优先复用已有WebView2；不可用时自动复用实际安装的Firefox/Chrome等浏览器，不下载或安装新内核。',
            '完整本机求解需EXE启动；首次直接双击HTML不能启动Python求解进程。EXE就绪后index.html直接进入同一仿真。',
            '每次打开/刷新默认1×；稳定停留5个仿真秒，起终点在下、阶数在上。',
            f'固定已验收快照：前四阶310条，五阶{report["orders"].get(5,0)}条独立双向配对方向；全五阶序列仅在精确证书通过时开放。',
            'motions中每对一个可读头部的TOML，正反解独立；系数为可逆压缩，没有舍入或重拟合。models共享物理模型。',
            '随包已有预建索引，首次只校验SHA并复制不可变快照，不重解析全部系数。索引缺失或损坏自动重建；缓存缺失且源未改可快速恢复。',
            '新文件或修改只有点击“检查轨迹更新”后激活。旧快照缺失且源已修改时不可伪造旧解，需手动检查更新。',
            '升级请保留trajectory_repository和recordings；本次不含个人记录。',
            '已面向Windows10/11 x64构建；不能只发HTML或EXE，必须整体转发文件夹或对应ZIP。']
        (folder/'使用说明.txt').write_text('\n\n'.join(notes)+'\n',encoding='utf-8-sig')
        (folder/'组件来源.txt').write_text('内含CPython及完整科学计算求解器，许可证在runtime内。WebView2 SDK许可在桌面许可目录；不包含或安装浏览器内核。\n',encoding='utf8')
    editions.compile_app('EditionRoot.cs',destination/'倒立摆实验室.exe')
    (destination/'使用说明.txt').write_text('轻量完整包：根EXE直接打开桌面版；网页版/打开网页版.exe打开网页。完整解压，无需安装。保留现场求解，复用已有浏览器，默认1×、稳态5秒。\n',encoding='utf-8-sig')
    (destination/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(folder=str(destination),**report),ensure_ascii=False),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination');p.add_argument('--seed',required=True);args=p.parse_args();build(args.destination,args.seed)
