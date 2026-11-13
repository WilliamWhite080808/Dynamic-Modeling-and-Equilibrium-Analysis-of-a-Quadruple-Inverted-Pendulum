"""Two shareable folders with one public EXE each; no automatic ZIP creation."""
from pathlib import Path
import argparse,json,os,shutil
from .build_editions import compile_app


def build(destination,seed):
    destination=Path(destination).resolve();seed=Path(seed).resolve()
    if destination.exists():raise ValueError('只构建到新的空目录，不能覆盖运行实例')
    destination.mkdir(parents=True)
    def copy(source,target):
        if 'runtime' in Path(source).parts:
            try:os.link(source,target);return target
            except OSError:pass
        return shutil.copy2(source,target)
    def ignore(directory,names):
        if Path(directory).name=='.cache':return [n for n in names if n!='trajectory-index.json']
        return [n for n in names if n in ('__pycache__','results','trajectory_repository','recordings')]
    report={'folder':str(destination),'editions':{},'archives_created':False,'private_records_included':False}
    for name,entry in (('网页版','打开网页版.exe'),('桌面版','倒立摆.exe')):
        outer=destination/name;outer.mkdir();inner=outer/'程序文件'
        source=seed/name
        if (source/'程序文件').is_dir():source=source/'程序文件'
        shutil.copytree(source,inner,ignore=ignore,copy_function=copy)
        # This redirect is generated at runtime; it is not a desktop entry.
        redirect=inner/'index.html'
        if redirect.exists():redirect.unlink()
        (inner/'results').mkdir()
        compile_app('CleanLauncher.cs',outer/entry)
        (inner/'使用说明.txt').write_text(
            name+'：双击上一级唯一的“'+entry+'”。完整转发该版本文件夹即可，不安装依赖。\n'
            '此目录是完整运行资源，请整体保留。motions放双向轨迹插件，models为共享模型；新插件点击“检查轨迹更新”激活。\n'
            '保留现场初值求解、动态图表、仓库、扰动、时间轴与核心区录制。默认1×，稳定停留5个仿真秒。\n'
            '桌面使用已有WebView2或浏览器，内部web文件是应用界面资源，并非另一个用户入口。\n',encoding='utf-8-sig')
        report['editions'][name]={'entry':entry,'resources':'程序文件','public_items':[entry,'程序文件']}
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination');p.add_argument('--seed',required=True);a=p.parse_args()
    print(json.dumps(build(a.destination,a.seed),ensure_ascii=False),flush=True)
