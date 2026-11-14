import ast,json
import pytest
from triple_pendulum import prune_dependencies as pruning


def test_function_closure_keeps_cold_branches_but_removes_unreferenced_code(tmp_path,monkeypatch):
    monkeypatch.setattr(pruning,'ROOT',tmp_path)
    runtime=tmp_path/'results/dependency-prune/runtime';module=runtime/'Lib/site-packages/scipy/example.py';module.parent.mkdir(parents=True)
    module.write_text('''# license retained
import math
import fractions
__all__ = ['entry', 'unused']
def shared(x):
    return math.sqrt(x)
def cold_branch(x):
    return shared(x) + 1
def entry(x):
    if x < 0:
        return cold_branch(-x)
    return shared(x)
def unused(x):
    return fractions.Fraction(x)
''',encoding='utf8')
    tool=pruning.Surgery(runtime,tmp_path/'evidence');result=tool.local_closure('scipy/example.py',{'entry'})
    value=module.read_text(encoding='utf8');scope={};exec(compile(value,str(module),'exec'),scope)
    assert result['removed']==['unused'] and 'import fractions' not in value
    assert scope['entry'](-9)==4 and scope['entry'](9)==3
    assert '# license retained' in value and scope['__all__']==['entry']


def test_guard_rejects_baseline_and_installed_library_surgery(tmp_path,monkeypatch):
    monkeypatch.setattr(pruning,'ROOT',tmp_path)
    with pytest.raises(ValueError,match='baseline'):pruning.Surgery(tmp_path/'dist/实验/runtime',tmp_path/'evidence')
    with pytest.raises(ValueError,match='baseline'):pruning.Surgery(tmp_path/'results/dependency-prune/baseline/runtime',tmp_path/'evidence')


def test_graph_retains_native_extensions_and_relative_import_parents(tmp_path):
    runtime=tmp_path/'runtime';site=runtime/'Lib/site-packages/pkg';site.mkdir(parents=True)
    (site/'__init__.py').write_text('from .algo import solve\n');(site/'algo.py').write_text('from . import _kernel\ndef solve():return _kernel.run()\n')
    native=site/'_kernel.cp311-win_amd64.pyd';native.write_bytes(b'not executed')
    app=tmp_path/'app/triple_pendulum';app.mkdir(parents=True);(app/'__init__.py').write_text('');(app/'server.py').write_text('from pkg import solve\n')
    graph=pruning.module_graph(runtime,app.parent)
    assert {'pkg','pkg.algo'}<=graph['modules'].keys()
    assert graph['native_modules']['pkg._kernel'].endswith('.pyd')
