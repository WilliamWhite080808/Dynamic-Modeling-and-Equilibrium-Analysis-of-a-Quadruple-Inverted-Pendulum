"""Publish a fresh full desktop only after the changed references are audited.

No active snapshot or original bank is modified. The runtime stays complete.
"""
import argparse,gzip,hashlib,json,shutil,subprocess,time
from pathlib import Path
from .motion_text import loads,dumps
from .motion_plugins import atomic,model_digest
from .model import Parameters
from .build_compact import runtime_modules,sha

ROOT=Path(__file__).resolve().parent.parent


def prepare(output,assets_path):
    output=Path(output).resolve()
    if output!=(ROOT/'results/supercompact').resolve():raise ValueError('Validation tools use the fixed results/supercompact workspace')
    if (output/'runtime').exists() or (output/'app').exists():raise ValueError('Do not overwrite an existing validation engine/app')
    assets=json.loads(Path(assets_path).read_bytes())
    for key in ('runtime','extractor','kernel'):
        if sha(assets[key])!=assets[key+'_sha256']:raise ValueError('Pinned asset changed: '+key)
    output.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(Path(assets['extractor']).resolve()),'x',str(Path(assets['runtime']).resolve()),'-o'+str(output),'-y'],check=True,capture_output=True)
    app=output/'app/triple_pendulum';app.mkdir(parents=True)
    for name in runtime_modules():shutil.copy2(ROOT/'triple_pendulum'/(name+'.py'),app/(name+'.py'))
    shutil.copy2(assets['kernel'],app/'_native.cp311-win_amd64.pyd')
    return dict(runtime=str(output/'runtime'),app=str(app.parent),runtime_sha256=assets['runtime_sha256'])


def fingerprints(reports):
    rows=[]
    for row in reports:
        n=row['n'];a,b=row['ends']
        rows.extend((n,s,t,row['runtime_hashes'][key]) for key,s,t in [('ab',a,b),('ba',b,a)])
    signatures={str(n):hashlib.sha256('\n'.join(sorted(f'{a}-{b}:{h}' for k,a,b,h in rows if k==n)).encode()).hexdigest() for n in range(1,6)}
    bank=hashlib.sha256('\n'.join(sorted(f'{n}-{a}-{b}:{h}' for n,a,b,h in rows)).encode()).hexdigest()
    return rows,signatures,bank


def plan_archive(report,direction,document):
    from .motion_lossy import reconstruct
    from .motion_plugins import digest,runtime
    i=0 if direction=='ab' else 1;ends=report['ends'];source,target=(ends if i==0 else ends[::-1])
    plan=reconstruct(document[direction],report['n'],source,target)
    if digest(runtime(plan))!=report['runtime_hashes'][direction]:raise ValueError('Cached plan cannot be regenerated exactly')
    plan.update(verification=report['physics'][i],direct_quality=report['direct'][i])
    worker=report['worker'];plan['worker_verification']=dict(individual=[worker['individual'][i]],continuous=[],rail_contacts=worker['rail_contacts'],live_planner_requests=worker['live_planner_requests'])
    return gzip.compress(json.dumps(plan,separators=(',',':')).encode(),compresslevel=3,mtime=0)


def tour_manifest(bank,output):
    from .control import analyze
    from .model import Plant
    import itertools
    reports=[json.loads(p.read_bytes()) for p in (bank/'reports').glob('*.json')]
    if len(reports)!=651 or not all(r['passed'] for r in reports):raise ValueError('Not every pair has new physical/Worker acceptance')
    for report in reports:
        ends=report['ends'];paths=[bank/'plans'/f'{report["n"]}-{s}-{t}.json.gz' for s,t in (ends,ends[::-1])]
        if any(not p.exists() for p in paths):
            raw=(bank/'motions'/report['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=report['sha256']:raise ValueError('Accepted plugin changed')
            document=loads(raw)
            for key,path in zip(('ab','ba'),paths):
                if not path.exists():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(plan_archive(report,key,document))
    rows,signatures,bank_sha=fingerprints(reports);designs={};entries=[]
    for n in range(1,6):
        plant=Plant(Parameters(n=n))
        for chars in itertools.product('UD',repeat=n):
            code=''.join(chars);designs[f'{n}-{code}']=analyze(plant,target=[0. if c=='U' else 3.141592653589793 for c in code])
    for n,a,b,h in sorted(rows):
        file=(bank/'plans'/f'{n}-{a}-{b}.json.gz').resolve();entries.append(dict(order=n,source=a,target=b,runtime_sha256=h,file=str(file),file_sha256=sha(file)))
    value=dict(orders=list(range(1,6)),signatures=signatures,bank_sha256=bank_sha,entries=entries,designs=designs)
    output.write_text(json.dumps(value,separators=(',',':')),encoding='utf8');return value


def build(bank,tour,output):
    bank=Path(bank).resolve();output=Path(output).resolve();certificate=json.loads(Path(tour).read_bytes())
    reports=[json.loads(p.read_bytes()) for p in (bank/'reports').glob('*.json')]
    if len(reports)!=651 or not all(r['passed'] for r in reports):raise ValueError('Incomplete new acceptance')
    rows,signatures,bank_sha=fingerprints(reports)
    if not certificate.get('passed') or certificate.get('bank_sha256')!=bank_sha or certificate.get('signatures')!=signatures:raise ValueError('No exact-bank new continuous certificate')
    if [(r['order'],r['edges']) for r in certificate['continuous']]!=[(n,2**n*(2**n-1)) for n in range(1,6)]:raise ValueError('Continuous coverage incomplete')
    if output.exists():raise ValueError('Refuse to replace any existing distribution')
    output.mkdir(parents=True);app=output/'程序文件';app.mkdir();source=ROOT/'dist/极简实验/桌面版/程序文件'
    shutil.copy2(source.parent/'倒立摆.exe',output/'倒立摆.exe')
    for name in ('runtime.7z','runtime.sha256','7zr.exe','界面.exe','Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll'):
        shutil.copy2(source/name,app/name)
    shutil.copytree(source/'许可',app/'许可');shutil.copytree(ROOT/'web',app/'web')
    (app/'triple_pendulum').mkdir()
    for name in runtime_modules():shutil.copy2(ROOT/'triple_pendulum'/(name+'.py'),app/'triple_pendulum'/(name+'.py'))
    shutil.copy2(source/'triple_pendulum/_native.cp311-win_amd64.pyd',app/'triple_pendulum/_native.cp311-win_amd64.pyd')
    shutil.copy2(ROOT/'launch.py',app/'launch.py');shutil.copy2(source/'index.html',app/'index.html')
    (app/'motions').mkdir();(app/'models').mkdir();(app/'results').mkdir()
    model=loads((source/'models/standard.toml').read_bytes());model['sequence_signatures']=signatures
    (app/'models/standard.toml').write_text(dumps(model),encoding='utf8');model_sha=model_digest(model);files={}
    for report in reports:
        name=report['file'];original=(source/'motions'/name).read_bytes();raw=(bank/'motions'/name).read_bytes()
        if hashlib.sha256(original).hexdigest()!=report['source_sha256'] or hashlib.sha256(raw).hexdigest()!=report['sha256']:raise ValueError('Accepted plugin changed')
        doc=loads(raw);raw=raw.replace(('model = "'+doc['model']+'"').encode(),('model = "'+model_sha+'"').encode(),1)
        if report['n']>=3 and len(raw)*10>len(original):raise ValueError('Ten percent bound failed')
        (app/'motions'/name).write_bytes(raw);fingerprint=hashlib.sha256(raw).hexdigest();n=report['n']
        directions={key:dict(runtime_sha256=report['runtime_hashes'][key],T=doc[key]['T'],proof=report['physics'][i]) for i,key in enumerate(('ab','ba'))}
        files[name]=dict(sha256=fingerprint,cache_sha256=fingerprint,n=n,ends=report['ends'],parameters=Parameters(n=n,**model['parameters']).dict(),directions=directions,ext='.toml',seed_source=name)
    atomic(app/'.cache/trajectory-index.json',dict(v=1,activated_at=time.time(),source_preload=True,model=model,files=files))
    old_bytes=sum(r['source_bytes'] for r in reports);new_bytes=sum(r['bytes'] for r in reports)
    if new_bytes*10>old_bytes:raise ValueError('Whole motion library exceeds ten percent')
    release=dict(experimental=True,lossy=True,complete_solver=True,one_click_start=True,requires_external_python=False,requires_network=False,
        pairs=651,directions=1302,orders={1:2,2:12,3:56,4:240,5:992},sequence_ready=[1,2,3,4,5],default_speed=1,stable_hold_seconds=5,
        trajectory_format='TOML v5; bounded quantization; full time nodes; regenerated TVLQR',original_motion_bytes=old_bytes,motion_bytes=new_bytes,motion_ratio=new_bytes/old_bytes,
        bank_sha256=bank_sha,continuous_certificate_sha256=sha(tour),runtime_sha256=sha(app/'runtime.7z'),entry='倒立摆.exe')
    (app/'release.toml').write_text(dumps(release),encoding='utf8')
    (app/'使用说明.txt').write_text('完整解压，双击上一级“倒立摆.exe”。随包保留完整现场求解和全部原功能，自动展开引擎，无需安装/联网。\n本版是有限有损轨迹实验，不是原始64位数值的无损复制；全部1302方向及连续序列已针对新参考重新验收。三至五阶每对文件不超过原v4的十分之一；一二阶优先精度。\n轨迹插件放motions，已有应用只有点击“检查轨迹更新”才激活新增；随包预建索引，缺失/损坏可重建。\n默认1×，稳态保持5个仿真秒。个人仓库和recordings请保留。复用已有WebView2或实际浏览器。\n',encoding='utf-8-sig')
    shutil.copy2(source/'组件来源.txt',app/'组件来源.txt')
    with (app/'组件来源.txt').open('a',encoding='utf8') as f:f.write('\n超级简使用有限精度新控制参考，逐条重新物理及实际Worker验收，不沿用原控制SHA或原序列证书。原始精确解在项目中独立保留。\n')
    shutil.copy2(ROOT/'docs/motion-plugin-format.md',app/'轨迹格式说明.md')
    return release


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','manifest','build']);parser.add_argument('--bank');parser.add_argument('--output',required=True);parser.add_argument('--tour');parser.add_argument('--assets',default='results/dependency-prune/assets.json');a=parser.parse_args()
    if a.mode=='prepare':result=prepare(a.output,a.assets)
    elif a.mode=='manifest':result=tour_manifest(Path(a.bank),Path(a.output))
    else:result=build(a.bank,a.tour,a.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('entries','designs')},ensure_ascii=False))
