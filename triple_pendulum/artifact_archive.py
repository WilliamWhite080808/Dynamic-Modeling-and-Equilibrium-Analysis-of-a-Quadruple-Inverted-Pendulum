"""Deduplicate historical numerical evidence before deleting obsolete builds.

This module archives data only. Deletion is a separate, explicitly reviewed step.
"""
from pathlib import Path,PurePosixPath
import argparse,datetime,gzip,hashlib,json,os,tarfile,zipfile
from .motion_text import dumps

OBSOLETE=('版本备份','fourth-order-upgrades','layout-five-second-acceptance','light-build',
          'editions-acceptance','light-acceptance','folder-acceptance','clean-delivery-acceptance',
          'portable-acceptance','compact-motion-prototype','ui-matrix-top','portable-source-check',
          'editions-build','qa-pip-cache','qa-npm-cache','clean-delivery-stage')
DATA={'.json','.toml','.npz','.npy','.mat','.csv','.tsv','.md','.txt','.log','.out','.err','.yaml','.yml','.pkl','.pickle','.png','.svg','.webm','.mp4'}


def useful(name):
    parts=PurePosixPath(str(name).replace('\\','/')).parts
    if any(p in ('runtime','engine','site-packages','node_modules','__pycache__','.git') for p in parts):return False
    if any(p.startswith(('profile-','web-profile-')) for p in parts):return False
    if '.cache' in parts:
        at=parts.index('.cache')
        if len(parts)<=at+1 or parts[at+1] not in ('motions','trajectory-index.json'):return False
    p=PurePosixPath(*parts)
    return p.suffix.lower() in DATA or p.name.endswith('.json.gz')


def finalize(root,additional=()):
    """Make the archive independent of mutable working data and capture late logs."""
    import tomllib
    root=Path(root).resolve();base=root/'results/history';index=base/'index.toml';doc=tomllib.loads(index.read_text('utf8'));report=json.loads((base/'verified.json').read_text('utf8'))
    rows={r['source']:r for r in doc['records']};objects={}
    def source_bytes(name):
        if '!/' in name:
            file,member=name.split('!/',1)
            if file.endswith(('.tar.gz','.tgz','.tar')):
                with tarfile.open(root/file,'r:*') as bundle:return bundle.extractfile(member).read()
            with zipfile.ZipFile(root/file) as z:return z.read(member)
        return (root/name).read_bytes()
    def store(raw):
        sha=hashlib.sha256(raw).hexdigest()
        if sha in objects:return objects[sha]
        gz=base/'objects'/sha[:2]/(sha+'.gz');plain=gz.with_suffix('.bin')
        if gz.exists():path=gz;compression='gzip'
        elif plain.exists():path=plain;compression='none'
        else:
            packed=gzip.compress(raw,6,mtime=0);compression='gzip' if len(packed)<len(raw) else 'none';path=gz if compression=='gzip' else plain;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(packed if compression=='gzip' else raw)
        obj=dict(object=path.relative_to(base).as_posix(),compression=compression);objects[sha]=obj;return obj
    for row in rows.values():
        if 'existing' not in row:continue
        hint=row.pop('existing');raw=(root/hint).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raw=source_bytes(row['source'])
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('A primary and its historical source both changed: '+row['source'])
        row.update(store(raw),canonical_hint=hint)
    def include(name,raw):
        sha=hashlib.sha256(raw).hexdigest();old=rows.get(name)
        if old and old['sha256']==sha:return
        if old:
            prior=dict(old);prior['source']=name+'@'+old['sha256'];rows[prior['source']]=prior
        rows[name]=dict(source=name,sha256=sha,bytes=len(raw),**store(raw))
    targets=[]
    for name in (*OBSOLETE,*additional):
        folder=root/'results'/name
        if not folder.resolve().is_relative_to(root/'results') or folder.resolve()==base:raise ValueError('Invalid archive source')
        if folder.exists():targets.append(str(folder.resolve()))
        for p in folder.rglob('*'):
            if not p.is_file():continue
            rel=p.relative_to(root).as_posix()
            extra=p.suffix.lower() in ('.html','.js') and p.stat().st_size>250000 and not any(s in p.parts for s in ('runtime','engine','node_modules','.cache'))
            if useful(rel) or extra:include(rel,p.read_bytes())
            elif p.suffix.lower()=='.zip' and 'runtime' not in p.parts and 'engine' not in p.parts:
                with zipfile.ZipFile(p) as z:
                    for item in z.infolist():
                        extra=PurePosixPath(item.filename).suffix.lower() in ('.html','.js') and item.file_size>250000 and not any(s in PurePosixPath(item.filename).parts for s in ('runtime','engine','.cache'))
                        if not item.is_dir() and (useful(item.filename) or extra):include(rel+'!/'+item.filename,z.read(item))
            elif p.name.endswith(('.tar.gz','.tgz','.tar')):
                try:
                    with tarfile.open(p,'r:*') as bundle:
                        for item in bundle:
                            if item.isfile() and useful(item.name):include(rel+'!/'+item.name,bundle.extractfile(item).read())
                except (tarfile.TarError,EOFError):include(rel,p.read_bytes())
        print('finalized',name,flush=True)
    verified=set()
    for row in rows.values():
        sha=row['sha256']
        if sha in verified:continue
        p=base/row['object'];raw=gzip.decompress(p.read_bytes()) if row['compression']=='gzip' else p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Final archive failed checksum')
        verified.add(sha)
    doc['records']=list(rows.values());temporary=index.with_suffix('.new');temporary.write_text(dumps(doc),encoding='utf8');temporary.replace(index)
    report.update(verified=True,independent_of_working_files=True,records=len(rows),all_record_bytes=sum(r['bytes'] for r in rows.values()),unique_archived_objects=len(verified),archived_bytes=sum(p.stat().st_size for p in (base/'objects').rglob('*') if p.is_file()),manifest_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),latest_archived_absolute_paths=targets)
    (base/'verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return report


def collect(root):
    root=Path(root).resolve();destination=root/'results/history';destination.mkdir(exist_ok=True)
    manifest=destination/'index.toml'
    if manifest.exists():raise ValueError('Archive exists; do not overwrite its provenance')
    primary={}
    for name in ('equilibrium_transitions','precomputed_swingups','trajectory_repository','recordings','docs'):
        for path in (root/name).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                primary.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(),path.relative_to(root).as_posix())
    records=[];objects={};archive_bytes=0;original_bytes=0
    def preserve(source,raw):
        nonlocal archive_bytes,original_bytes
        sha=hashlib.sha256(raw).hexdigest();record=dict(source=source,sha256=sha,bytes=len(raw));original_bytes+=len(raw)
        if sha in primary:record['existing']=primary[sha]
        else:
            if sha not in objects:
                payload=gzip.compress(raw,compresslevel=6,mtime=0);compressed=len(payload)<len(raw)
                path=destination/'objects'/sha[:2]/(sha+('.gz' if compressed else '.bin'));path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload if compressed else raw)
                objects[sha]=(path,compressed);archive_bytes+=path.stat().st_size
            path,compressed=objects[sha];record.update(object=path.relative_to(destination).as_posix(),compression='gzip' if compressed else 'none')
        records.append(record)
    targets=[]
    for name in OBSOLETE:
        directory=root/'results'/name
        if not directory.exists():continue
        assert directory.resolve().is_relative_to(root/'results');targets.append(str(directory.resolve()))
        for path in directory.rglob('*'):
            if not path.is_file():continue
            relative=path.relative_to(root).as_posix()
            if useful(relative):preserve(relative,path.read_bytes())
            elif path.suffix.lower()=='.zip' and 'runtime' not in path.parts and 'engine' not in path.parts:
                with zipfile.ZipFile(path) as bundle:
                    for item in bundle.infolist():
                        if not item.is_dir() and useful(item.filename):preserve(relative+'!/'+item.filename,bundle.read(item))
            elif path.name.endswith(('.tar.gz','.tgz','.tar')):
                try:
                    with tarfile.open(path,'r:*') as bundle:
                        for item in bundle:
                            if item.isfile() and useful(item.name):preserve(relative+'!/'+item.name,bundle.extractfile(item).read())
                except (tarfile.TarError,EOFError):preserve(relative,path.read_bytes())
        print('archived',name,'records',len(records),'unique objects',len(objects),flush=True)
    # A second complete read verifies recoverability before any deletion occurs.
    for sha,(path,compressed) in objects.items():
        raw=gzip.decompress(path.read_bytes()) if compressed else path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Archive checksum mismatch: '+str(path))
    doc=dict(v=1,created_at=datetime.datetime.now().astimezone().isoformat(),records=records)
    manifest.write_text(dumps(doc),encoding='utf8')
    report=dict(verified=True,records=len(records),unique_archived_objects=len(objects),archived_bytes=archive_bytes,all_record_bytes=original_bytes,obsolete_absolute_paths=targets,manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
    (destination/'verified.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (destination/'README.md').write_text('此处保存旧构建独有的数值结果、证明、日志、用户记录与图像。index.toml列出每个原路径和SHA；相同内容只存一次，已在主数据目录中的文件直接引用。objects全部重读校验后才允许删除旧构建。原项目日志与对话文档仍原样保留。\n恢复：python -m triple_pendulum.artifact_archive restore 原路径 目标文件\n',encoding='utf8')
    return report


def restore(source,target):
    import tomllib
    root=Path(__file__).resolve().parent.parent;archive=root/'results/history';doc=tomllib.loads((archive/'index.toml').read_text('utf8'))
    row=next(r for r in doc['records'] if r['source']==source)
    raw=(root/row['existing']).read_bytes() if 'existing' in row else (archive/row['object']).read_bytes()
    if row.get('compression')=='gzip':raw=gzip.decompress(raw)
    if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Archived result is corrupt')
    target=Path(target)
    if target.exists():raise ValueError('Refusing to overwrite an existing file')
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('collect','finalize','restore'));p.add_argument('paths',nargs='*');a=p.parse_args()
    if a.action=='collect':print(json.dumps(collect(Path(__file__).resolve().parent.parent),ensure_ascii=False))
    elif a.action=='finalize':print(json.dumps(finalize(Path(__file__).resolve().parent.parent,a.paths),ensure_ascii=False))
    else:restore(*a.paths)
