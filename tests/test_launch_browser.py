import importlib.util
from pathlib import Path

def launcher():
    spec=importlib.util.spec_from_file_location('folder_launcher',Path(__file__).resolve().parent.parent/'launch.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def test_broken_browser_is_skipped_and_next_executable_opens(tmp_path,monkeypatch):
    mod=launcher();monkeypatch.setattr(mod,'ROOT',tmp_path);monkeypatch.delenv('PENDULUM_TEST_FIREFOX_PROFILE',raising=False)
    monkeypatch.setattr(mod,'browser_candidates',lambda:['broken.exe','firefox.exe']);calls=[]
    class Process:
        def poll(self):return None
    def popen(args,**kwargs):
        calls.append(args)
        if args[0]=='broken.exe':raise FileNotFoundError('stale browser registration')
        return Process()
    monkeypatch.setattr(mod.subprocess,'Popen',popen);monkeypatch.setattr(mod.time,'sleep',lambda _:None)
    assert mod.open_browser('http://127.0.0.1:8767')=='firefox.exe'
    assert len(calls)==2
    assert (tmp_path/'.cache/browser.txt').read_text()=='firefox.exe'

def test_no_browser_has_visible_error_instead_of_false_success(monkeypatch):
    import pytest
    mod=launcher();monkeypatch.setattr(mod,'browser_candidates',lambda:[])
    with pytest.raises(RuntimeError,match='桌面版'):mod.open_browser('http://127.0.0.1:8767')
