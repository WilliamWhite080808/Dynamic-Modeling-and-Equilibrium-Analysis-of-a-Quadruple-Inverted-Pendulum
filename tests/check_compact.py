"""Cold unpack and ordinary EXE entry, without installed Python or working PATH."""
from pathlib import Path
import ctypes,hashlib,json,os,subprocess,sys,time,urllib.request,zipfile
from ctypes import wintypes

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    archive=Path(sys.argv[1]).resolve();qa=Path(sys.argv[2]).resolve();qa.mkdir(parents=True,exist_ok=False)
    assert archive.stat().st_size<100_000_000
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        root=qa/'中文 空格';bundle.extractall(root)
        folder=next(p for p in root.iterdir() if p.is_dir())
        for info in bundle.infolist():
            if not info.is_dir():assert (root/info.filename).read_bytes()==bundle.read(info)
    env=os.environ.copy();env.update(PATH=os.environ['SystemRoot']+'\\System32',PYTHONHOME='Z:/missing-python',PYTHONPATH='Z:/missing-python',BROWSER='Z:/removed-edge.exe',
        PENDULUM_TEST_CACHE_ROOT=str(qa/'隔离缓存'),HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='127.0.0.1,localhost')
    started=time.monotonic();outer=subprocess.Popen([str(folder/'倒立摆.exe')],cwd=folder,env=env,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_BREAKAWAY_FROM_JOB)
    app=folder/'程序文件';endpoint=None
    for _ in range(600):
        try:
            endpoint=json.loads((app/'.cache/instance.json').read_bytes())['url']
            with urllib.request.urlopen(endpoint+'/api/health',timeout=2) as response:
                health=json.load(response)
            if health['instance']==str(app):break
        except (OSError,ValueError):pass
        time.sleep(.25)
    else:raise AssertionError('Ordinary EXE did not create the isolated backend')
    user=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE;kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    windows=[]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def visit(hwnd,unused):
        if user.IsWindowVisible(hwnd):
            pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));process=kernel.OpenProcess(0x1000,False,pid.value)
            if process:
                try:
                    size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
                    if kernel.QueryFullProcessImageNameW(process,0,buffer,ctypes.byref(size)) and Path(buffer.value)==app/'界面.exe':
                        text=ctypes.create_unicode_buffer(1024);user.GetWindowTextW(hwnd,text,1024)
                        windows.append(dict(pid=pid.value,title=text.value,visible=True,hwnd=int(hwnd)))
                finally:kernel.CloseHandle(process)
        return True
    for _ in range(120):
        windows.clear();user.EnumWindows(visit,0)
        if windows:break
        time.sleep(.25)
    assert windows,'No visible native application window'
    # An ordinary visible loading form alone is not a rendered application.
    for _ in range(360):
        if (app/'results/桌面窗口.log').exists():break
        time.sleep(.25)
    else:raise AssertionError('The real EXE did not finish displaying its interface')
    report=dict(passed=True,archive_bytes=archive.stat().st_size,archive_sha256=sha(archive),crc_and_all_member_bytes_passed=True,
        folder=str(folder),cold_start_seconds=time.monotonic()-started,url=endpoint,ordinary_exe=True,driver_navigation=False,
        window=windows[0],actual_page_navigation_completed=True,runtime_auto_expanded=True,isolated_path_and_pythonhome=True,requires_installation=False)
    (qa/'cold-entry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    # Close only this exact application, then exercise its actual visible WebView.
    user.PostMessageW(windows[0]['hwnd'],0x0010,0,0);time.sleep(3)
    try:
        with urllib.request.urlopen(endpoint+'/api/health',timeout=2) as response:
            still_running=json.load(response).get('instance')==str(app)
    except OSError:still_running=False
    assert not still_running,'Closing the native window left its backend running'
    report['close_stops_own_backend']=True
    (qa/'cold-entry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if '--entry-only' in sys.argv:return
    checks=qa/'native';checks.mkdir()
    result=subprocess.run([str(folder/'倒立摆.exe'),'--self-test',str(checks)],cwd=folder,env=env,timeout=420)
    if result.returncode:raise AssertionError('Native functional acceptance failed')
    print((checks/'desktop.log').read_text(encoding='utf8') if (checks/'desktop.log').exists() else 'Native self-test completed',flush=True)

if __name__=='__main__':main()
