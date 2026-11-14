"""Application-specific SciPy fork: local function closure plus import closure.

Only operates on the isolated dependency-prune work tree. Numerical function
bodies and native binaries are not rewritten. No missing-function stubs.
"""
from pathlib import Path
import argparse,ast,hashlib,importlib.util,json,os,shutil

ROOT=Path(__file__).resolve().parent.parent
DEFS=(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)
MARK='# PendulumLab isolated dependency variant; upstream algorithms unchanged.\n'


def digest(raw):return hashlib.sha256(raw).hexdigest()


class Surgery:
    def __init__(self,runtime,evidence):
        self.runtime=Path(runtime).resolve();self.evidence=Path(evidence).resolve()
        allowed=(ROOT/'results/dependency-prune').resolve()
        if not self.runtime.is_relative_to(allowed) or self.runtime.is_relative_to(allowed/'baseline'):raise ValueError('Refuse to modify a baseline or installed library')
        self.site=self.runtime/'Lib/site-packages';self.evidence.mkdir(parents=True,exist_ok=True);self.changes=[]

    def original(self,relative):
        p=self.site/relative;backup=self.evidence/'originals'/relative
        if not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(p.read_bytes())
        return backup.read_text(encoding='utf-8-sig')

    def write(self,relative,text,reason):
        path=self.site/relative;old=path.read_bytes() if path.exists() else b''
        if path.exists():self.original(relative)
        raw=text.encode('utf8')
        if raw!=old:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            self.changes.append(dict(file=relative,reason=reason,before_bytes=len(old),after_bytes=len(raw),before_sha256=digest(old),after_sha256=digest(raw)))

    def cumulative_changes(self):
        rows=[]
        for p in sorted((self.evidence/'originals').rglob('*')):
            if not p.is_file():continue
            relative=p.relative_to(self.evidence/'originals').as_posix();current=self.site/relative
            if not current.exists():continue
            old=p.read_bytes();new=current.read_bytes()
            if relative=='scipy/optimize/_pendulum_support.py':old=b''
            if new!=old:rows.append(dict(file=relative,before_bytes=len(old),after_bytes=len(new),before_sha256=digest(old),after_sha256=digest(new)))
        return rows

    def support(self):
        # These are exact original class/helper bodies, not replacements for
        # validation or numerical work. Avoid importing every optimizer to get
        # the shared result and Bounds containers.
        snippets=[]
        for rel,roots in [('scipy/optimize/_optimize.py',{'OptimizeResult','OptimizeWarning'}),('scipy/optimize/_constraints.py',{'Bounds'})]:
            text=self.original(rel);tree=ast.parse(text);defs={n.name:n for n in tree.body if isinstance(n,DEFS)};wanted=set(roots)
            while True:
                used={x.id for name in wanted for x in ast.walk(defs[name]) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Load)}
                extra=(used&defs.keys())-wanted
                if not extra:break
                wanted|=extra
            snippets.extend(ast.get_source_segment(text,n) for n in tree.body if isinstance(n,DEFS) and n.name in wanted)
        self.write('scipy/optimize/_pendulum_support.py',MARK+'# Original SciPy 1.11.4 BSD-licensed definitions; see scipy dist-info.\nimport numpy as np\nfrom scipy.sparse import issparse\n\n'+'\n\n'.join(snippets)+'\n','Extract exact shared containers and their helper closure')

    def shims(self):
        self.support()
        shims={
          'scipy/optimize/__init__.py':'from ._pendulum_support import OptimizeResult, OptimizeWarning\nfrom ._lsq.least_squares import least_squares\n__all__ = ["least_squares", "OptimizeResult", "OptimizeWarning"]\n',
          'scipy/optimize/_lsq/__init__.py':'from .least_squares import least_squares\n__all__ = ["least_squares"]\n',
          'scipy/sparse/linalg/_isolve/__init__.py':'from .lsmr import lsmr\n__all__ = ["lsmr"]\n',
          'scipy/sparse/linalg/__init__.py':'from ._interface import LinearOperator, aslinearoperator\nfrom ._isolve.lsmr import lsmr\nfrom ._onenormest import onenormest\nfrom ._dsolve.linsolve import spsolve, splu, factorized\n__all__ = [n for n in dir() if not n.startswith("_")]\n',
          'scipy/linalg/__init__.py':'''from numpy.linalg import LinAlgError
from ._cythonized_array_utils import bandwidth
from ._misc import norm
from ._basic import solve, solve_triangular, inv, lstsq, matrix_balance, pinv
from ._decomp import eig, eigh, eigvals, eigvalsh
from ._decomp_svd import svd, svdvals
from ._decomp_qr import qr
from ._decomp_lu import lu, lu_factor, lu_solve
from ._decomp_cholesky import cholesky, cho_factor, cho_solve
from .blas import get_blas_funcs
from .lapack import get_lapack_funcs
from ._decomp_qz import ordqz
from ._matfuncs import expm
from ._solvers import solve_continuous_are, solve_discrete_are
from ._special_matrices import block_diag, kron, toeplitz
__all__ = [n for n in dir() if not n.startswith('_')]
'''}
        for path,text in shims.items():self.write(path,MARK+text,'Keep application exports; remove eager unrelated algorithm imports')
        path='scipy/optimize/_lsq/least_squares.py'
        self.write(path,self.original(path).replace('from scipy.optimize._minimize import Bounds','from scipy.optimize._pendulum_support import Bounds'),'Use the exact extracted Bounds class, without minimize-family imports')
        path='scipy/sparse/__init__.py';text=self.original(path)
        text=text.replace('from . import csgraph','# Graph algorithms are not an application API.')
        self.write(path,MARK+text,'Do not eagerly load graph algorithms')

    def local_closure(self,relative,roots):
        text=self.original(relative);tree=ast.parse(text);defs={n.name:n for n in tree.body if isinstance(n,DEFS)}
        keep=set(roots)&defs.keys();top=[n for n in tree.body if not isinstance(n,(*DEFS,ast.Import,ast.ImportFrom))]
        aliases=[]
        for n in top:
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Name) and n.value.id in defs and all(isinstance(t,ast.Name) and t.id not in roots for t in n.targets):aliases.append(n)
        top=[n for n in top if n not in aliases]
        while True:
            used={x.id for node in [*top,*(defs[name] for name in keep)] for x in ast.walk(node) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Load)}|set(roots)
            extra=(used&defs.keys())-keep
            if not extra:break
            keep|=extra
        edits=[]
        for n in tree.body:
            if isinstance(n,DEFS) and n.name not in keep:
                first=min([n.lineno,*[d.lineno for d in n.decorator_list]])
                edits.append((first,n.end_lineno,''))
            elif n in aliases:edits.append((n.lineno,n.end_lineno,''))
            elif isinstance(n,(ast.Import,ast.ImportFrom)) and not (isinstance(n,ast.ImportFrom) and n.module=='__future__'):
                names=[a for a in n.names if a.name=='*' or (a.asname or a.name.split('.')[0]) in used]
                if len(names)!=len(n.names):
                    if not names:replacement=''
                    else:
                        prefix='import ' if isinstance(n,ast.Import) else 'from '+'.'*n.level+(n.module or '')+' import '
                        replacement=prefix+', '.join(a.name+(' as '+a.asname if a.asname else '') for a in names)+'\n'
                    edits.append((n.lineno,n.end_lineno,replacement))
            elif isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__all__' for t in n.targets) and isinstance(n.value,(ast.List,ast.Tuple)):
                available=keep|used
                entries=[v.value for v in n.value.elts if isinstance(v,ast.Constant) and isinstance(v.value,str) and v.value in available]
                edits.append((n.lineno,n.end_lineno,'__all__ = '+repr(entries)+'\n'))
        lines=text.splitlines(keepends=True)
        for first,last,value in sorted(edits,reverse=True):lines[first-1:last]=[value]
        result=MARK+''.join(lines)
        if relative=='scipy/optimize/_lsq/least_squares.py':
            result=result.replace('from scipy.optimize._minimize import Bounds','from scipy.optimize._pendulum_support import Bounds')
        ast.parse(result)
        self.write(relative,result,'Transitive module-global function closure; keep full retained bodies and branches')
        return dict(file=relative,functions_before=len(defs),kept=sorted(keep),removed=sorted(defs.keys()-keep))

    def reduce(self,app,coverage):
        metadata=self.site/'scipy-1.11.4.dist-info/METADATA'
        if not metadata.exists() or '\nVersion: 1.11.4\n' not in metadata.read_text(encoding='utf8'):
            raise ValueError('These source edits are pinned to SciPy 1.11.4')
        self.shims()
        specs={
          'scipy/linalg/_solvers.py':{'solve_continuous_are','solve_discrete_are'},
          'scipy/linalg/_matfuncs.py':{'expm'},
          'scipy/linalg/_special_matrices.py':{'block_diag','kron','toeplitz'},
          'scipy/linalg/_basic.py':{'solve','solve_triangular','inv','lstsq','matrix_balance','pinv'},
          'scipy/sparse/linalg/_isolve/lsqr.py':{'_sym_ortho'},
          'scipy/sparse/linalg/_matfuncs.py':set(),
          'scipy/linalg/_decomp.py':{'eig','eigh','eigvals','eigvalsh','_asarray_validated'},
          'scipy/linalg/_decomp_svd.py':{'svd','svdvals'},
          'scipy/linalg/_decomp_qr.py':{'qr'},
          'scipy/linalg/_decomp_qz.py':{'ordqz'},
          'scipy/linalg/_decomp_cholesky.py':{'cholesky','cho_factor','cho_solve'},
        }
        rows=[self.local_closure(path,roots) for path,roots in specs.items()]
        if coverage:
            # Derive roots from all retained imports/attribute references and
            # observed calls. Dynamic namespace modules are protected whole.
            graph=module_graph(self.runtime,app)
            for prefix in ('scipy/linalg/','scipy/optimize/_lsq/','scipy/sparse/linalg/','scipy/_lib/'):
                for path in (self.site/prefix).rglob('*.py'):
                    relative=path.relative_to(self.site).as_posix()
                    if path.name=='__init__.py' or '.tests.' in relative:continue
                    name=module_name(relative)
                    if name not in graph['modules']:continue
                    text=self.original(relative);tree=ast.parse(text)
                    if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('globals','locals','eval','exec') for n in ast.walk(tree)):continue
                    specs.setdefault(relative,set())
            roots=requested_symbols(self.runtime,app,graph,specs,coverage)
            rows=[self.local_closure(path,set(seed)|roots.get(module_name(path),set())) for path,seed in specs.items()]
        for p in self.runtime.rglob('__pycache__'):
            if p.is_dir():shutil.rmtree(p)
        report=dict(version=1,isolated=True,numerical_bodies_unchanged=True,changes=self.cumulative_changes(),function_closures=rows)
        (self.evidence/'surgery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return report


def module_name(relative):
    name=relative.removesuffix('.py').replace('/','.')
    return name.removesuffix('.__init__')


def requested_symbols(runtime,app,graph,specs,coverage):
    site=Path(runtime)/'Lib/site-packages';targets={module_name(k) for k in specs};wanted={n:set() for n in targets}
    packages={name for name,path in graph['modules'].items() if path.endswith('/__init__.py')}
    sources=[(name,site/path) for name,path in graph['modules'].items()]+[('triple_pendulum.'+p.stem,p) for p in (Path(app)/'triple_pendulum').glob('*.py')]
    for name,path in sources:
        tree=ast.parse(path.read_text(encoding='utf-8-sig'));package=name if name in packages else name.rpartition('.')[0];bindings={}
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):
                for a in n.names:bindings[a.asname or a.name.split('.')[0]]=a.name if a.asname else a.name.split('.')[0]
            elif isinstance(n,ast.ImportFrom):
                try:base=importlib.util.resolve_name('.'*n.level+(n.module or ''),package) if n.level else n.module or ''
                except (ImportError,ValueError):continue
                for a in n.names:
                    if base in targets:
                        if a.name=='*':
                            source=site/(base.replace('.','/')+'.py')
                            wanted[base]|={x.name for x in ast.parse(source.read_text(encoding='utf8')).body if isinstance(x,DEFS) and not x.name.startswith('_')}
                        else:wanted[base].add(a.name)
                    bindings[a.asname or a.name]=base+'.'+a.name
        for n in ast.walk(tree):
            if isinstance(n,ast.Attribute):
                parts=[];node=n
                while isinstance(node,ast.Attribute):parts.append(node.attr);node=node.value
                if isinstance(node,ast.Name) and node.id in bindings:
                    full=bindings[node.id]+'.'+'.'.join(reversed(parts));base,_,member=full.rpartition('.')
                    if base in wanted:wanted[base].add(member)
    for filename in coverage:
        doc=json.loads(Path(filename).read_bytes())
        for entry in doc['functions']:
            relative,qualname=entry.rsplit(':',1)
            if relative.startswith('Lib/site-packages/'):
                name=module_name(relative[len('Lib/site-packages/'):])
                if name in wanted:wanted[name].add(qualname.split('.')[0])
    return wanted


def module_graph(runtime,app):
    """Conservative literal import closure, including retained branch imports.

    Dynamic imports and C extension imports must be augmented by runtime traces
    before deleting modules. This function reports, never guesses them away.
    """
    runtime=Path(runtime).resolve();app=Path(app).resolve();site=runtime/'Lib/site-packages';files={};packages=set()
    for base,prefix in ((site,''),(app/'triple_pendulum','triple_pendulum')):
        for p in base.rglob('*.py'):
            if '__pycache__' in p.parts:continue
            parts=list(p.relative_to(base).with_suffix('').parts)
            if parts[-1]=='__init__':parts.pop();is_package=True
            else:is_package=False
            name='.'.join(([prefix] if prefix else [])+parts)
            if name:files[name]=p
            if is_package:packages.add(name)
    natives={}
    for p in site.rglob('*.pyd'):
        parts=list(p.relative_to(site).parts);parts[-1]=parts[-1].split('.')[0];natives['.'.join(parts)]=p
    roots=['triple_pendulum.'+p.stem for p in (app/'triple_pendulum').glob('*.py') if p.stem!='__init__']+['triple_pendulum']
    pending=list(roots);seen=set();external=set();edges={};native_needed=set()
    def request(name):
        if not name:return
        parts=name.split('.')
        for i in range(1,len(parts)+1):
            item='.'.join(parts[:i])
            if item in files and item not in seen:pending.append(item)
            if item in natives:native_needed.add(item)
    while pending:
        name=pending.pop()
        if name in seen:continue
        if name not in files:external.add(name);continue
        seen.add(name);edges[name]=set();package=name if name in packages else name.rpartition('.')[0]
        try:tree=ast.parse(files[name].read_text(encoding='utf-8-sig'))
        except (SyntaxError,UnicodeError):continue
        def dependency(dep):
            if not dep:return
            edges[name].add(dep);request(dep)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                for alias in node.names:dependency(alias.name)
            elif isinstance(node,ast.ImportFrom):
                try:base=importlib.util.resolve_name('.'*node.level+(node.module or ''),package) if node.level else node.module or ''
                except (ValueError,ImportError):continue
                dependency(base)
                for alias in node.names:
                    if alias.name!='*' and base+'.'+alias.name in (files.keys()|natives.keys()):dependency(base+'.'+alias.name)
            elif isinstance(node,ast.Call) and isinstance(node.func,(ast.Name,ast.Attribute)):
                called=node.func.id if isinstance(node.func,ast.Name) else node.func.attr
                if called in ('import_module','__import__') and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                    target=node.args[0].value
                    if not target.startswith('.'):dependency(target)
    return dict(modules={name:files[name].relative_to(site).as_posix() for name in sorted(seen) if files[name].is_relative_to(site)},
        native_modules={name:natives[name].relative_to(site).as_posix() for name in sorted(native_needed)},graph={k:sorted(v) for k,v in edges.items()})


def trim_files(runtime,app,evidence,coverages):
    runtime=Path(runtime).resolve();site=runtime/'Lib/site-packages';evidence=Path(evidence).resolve()
    allowed=(ROOT/'results/dependency-prune').resolve()
    if not runtime.is_relative_to(allowed) or runtime.is_relative_to(allowed/'baseline'):raise ValueError('Refuse baseline deletion')
    graph=module_graph(runtime,app);keep=set(graph['modules'].values())|set(graph['native_modules'].values())
    for file in coverages:
        for relative in json.loads(Path(file).read_bytes())['modules'].values():
            if relative.startswith('Lib/site-packages/'):keep.add(relative[len('Lib/site-packages/'):])
    # Compiled extension initializers and Cython C-APIs are opaque to AST.
    # Their actual module loads are unioned above; binary implementations are
    # retained intact. License/metadata files are always retained.
    code={'.py','.pyc','.pyd','.pyi','.pyx','.pxd','.pxi','.pyf','.h','.c','.cpp','.f','.f90','.o','.a'}
    removed=[]
    for package in ('scipy','numpy'):
        for path in sorted((site/package).rglob('*')):
            if not path.is_file():continue
            rel=path.relative_to(site).as_posix()
            if 'license' in path.name.lower() or 'notice' in path.name.lower():continue
            if path.suffix in code and rel not in keep:
                raw=path.read_bytes();removed.append(dict(file=rel,bytes=len(raw),sha256=digest(raw)));path.unlink()
    # These belong to installer/audio/SQLite applications. This product uses
    # JSON/TOML and browser recording, not Python SQLite, MSI or audio playback.
    for name in ('_sqlite3.pyd','sqlite3.dll','_msi.pyd','winsound.pyd','pythonw.exe','python.cat'):
        path=runtime/name
        if path.exists():
            raw=path.read_bytes();removed.append(dict(file=name,bytes=len(raw),sha256=digest(raw)));path.unlink()
    for path in sorted(runtime.rglob('__pycache__'),reverse=True):
        if path.is_dir():shutil.rmtree(path)
    report=dict(removed_files=len(removed),removed_bytes=sum(r['bytes'] for r in removed),files=removed,
        kept_modules=sorted(keep),static_and_dynamic_union=True,native_function_bodies_not_edited=True)
    (evidence/'file-pruning.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('runtime');p.add_argument('--evidence',required=True);p.add_argument('--app',required=True);p.add_argument('--coverage',action='append',default=[]);p.add_argument('--trim-files',action='store_true');a=p.parse_args()
    if a.trim_files:
        if not a.coverage:p.error('Runtime coverage is required before file deletion')
        report=trim_files(a.runtime,a.app,a.evidence,a.coverage);print(json.dumps({k:v for k,v in report.items() if k not in ('files','kept_modules')}));raise SystemExit
    report=Surgery(a.runtime,a.evidence).reduce(a.app,a.coverage);graph=module_graph(a.runtime,a.app)
    (Path(a.evidence)/'static-import-closure.json').write_text(json.dumps(graph,indent=2),encoding='utf8')
    print(json.dumps(dict(modified_files=len(report['changes']),functions_removed=sum(len(r['removed']) for r in report['function_closures']),static_modules=len(graph['modules']))))
