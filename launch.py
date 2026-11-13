"""Robust folder-local service launcher; browser opening has real fallbacks."""
from pathlib import Path
import json,os,socket,subprocess,sys,time,urllib.request,urllib.parse,shutil,traceback
ROOT=Path(__file__).resolve().parent
HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def phase(text):
    (ROOT/'.cache').mkdir(exist_ok=True)
    (ROOT/'.cache/startup.txt').write_text(text,encoding='utf8')

def healthy(url):
    try:
        u=urllib.parse.urlsplit(url)
        if u.scheme!='http' or u.hostname!='127.0.0.1' or not 8765<=u.port<8865:return False
        with HTTP.open(url+'/api/health',timeout=.8) as response:data=json.load(response)
        return data.get('status')=='ok' and os.path.normcase(data.get('instance',''))==os.path.normcase(str(ROOT))
    except Exception:return False

def browser_candidates():
    candidates=[]
    if os.name=='nt':
        import winreg,ctypes
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice') as key:prog=winreg.QueryValueEx(key,'ProgId')[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,prog+r'\shell\open\command') as key:cmd=winreg.QueryValueEx(key,None)[0]
            argc=ctypes.c_int();parse=ctypes.windll.shell32.CommandLineToArgvW;parse.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)];parse.restype=ctypes.POINTER(ctypes.c_wchar_p);argv=parse(cmd,ctypes.byref(argc))
            if argc.value:candidates.append(argv[0])
            free=ctypes.windll.kernel32.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p;free(ctypes.cast(argv,ctypes.c_void_p))
        except OSError:pass
        for exe in ('firefox.exe','chrome.exe','msedge.exe','brave.exe','vivaldi.exe','opera.exe'):
            for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
                for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hive,r'Software\Microsoft\Windows\CurrentVersion\App Paths'+'\\'+exe,0,winreg.KEY_READ|view) as key:candidates.append(winreg.QueryValueEx(key,None)[0])
                    except OSError:pass
    for env in ('ProgramW6432','ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
        base=Path(os.environ.get(env,'C:/missing'))
        for relative in ('Mozilla Firefox/firefox.exe','Google/Chrome/Application/chrome.exe','Microsoft/Edge/Application/msedge.exe','BraveSoftware/Brave-Browser/Application/brave.exe','Programs/Opera/opera.exe'):
            candidates.append(str(base/relative))
    for name in ('firefox','chrome','msedge','brave','vivaldi','opera'):
        found=shutil.which(name)
        if found:candidates.append(found)
    result=[]
    for path in candidates:
        path=os.path.expandvars(path).strip('"')
        if Path(path).is_file() and os.path.normcase(path) not in [os.path.normcase(p) for p in result]:result.append(path)
    return result

def open_browser(url,desktop=False):
    errors=[]
    for path in browser_candidates():
        try:
            command=[path,url]
            if desktop:
                command=[path,'--new-window',url] if Path(path).name.lower()=='firefox.exe' else [path,'--app='+url,'--new-window']
            profile=os.environ.get('PENDULUM_TEST_FIREFOX_PROFILE')
            if profile and Path(path).name.lower()=='firefox.exe':command=[path,'--no-remote','--marionette','--profile',profile,url]
            proc=subprocess.Popen(command,close_fds=True)
            time.sleep(.35)
            if proc.poll() not in (None,0):raise RuntimeError('浏览器退出码 '+str(proc.returncode))
            phase('已打开浏览器：'+Path(path).name)
            (ROOT/'.cache/browser.txt').write_text(path,encoding='utf8');return path
        except OSError as error:errors.append(str(error))
        except RuntimeError as error:errors.append(str(error))
    raise RuntimeError('未找到实际可用的浏览器或桌面引擎，请检查浏览器是否被移除。'+('；'.join(errors[-2:])))

def ensure_service():
    cache=ROOT/'.cache';cache.mkdir(exist_ok=True);record=cache/'instance.json'
    lock=(cache/'launcher.lock').open('a+b')
    if lock.tell()==0:lock.write(b'0');lock.flush()
    acquired=False
    if os.name=='nt':
        import msvcrt
        deadline=time.monotonic()+360
        while not acquired:
            try:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);acquired=True
            except OSError:
                phase('正在等待已启动的实验室…')
                if time.monotonic()>deadline:raise RuntimeError('另一启动进程长时间无响应，请查看 results/启动.log')
                time.sleep(.25)
    url=None;pid=None
    try:
        if record.exists():
            try:
                saved=json.loads(record.read_text(encoding='utf8'));candidate=saved['url']
                if healthy(candidate):url=candidate;pid=saved.get('pid')
            except Exception:pass
        if url is None:
            for port in range(8765,8865):
                candidate='http://127.0.0.1:'+str(port)
                if healthy(candidate):url=candidate;break
                with socket.socket() as reserve:
                    try:reserve.bind(('127.0.0.1',port))
                    except OSError:continue
                phase('正在启动本地求解服务…')
                results=ROOT/'results';results.mkdir(exist_ok=True)
                env=os.environ.copy();env.update(PENDULUM_PORT=str(port),PYTHONNOUSERSITE='1',PYTHONUTF8='1',NUMBA_CACHE_DIR=str(cache/'numba'),TMP=str(cache),TEMP=str(cache))
                flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                with (results/'server.log').open('a',encoding='utf8') as log:
                    proc=subprocess.Popen([sys.executable,'-m','triple_pendulum.server'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=flags,close_fds=True)
                record.write_text(json.dumps(dict(url=candidate,pid=proc.pid)),encoding='utf8')
                deadline=time.monotonic()+360
                while time.monotonic()<deadline:
                    if healthy(candidate):url=candidate;pid=proc.pid;break
                    if proc.poll() is not None:
                        with socket.socket() as probe:occupied=probe.connect_ex(('127.0.0.1',port))==0
                        if occupied:break
                        raise RuntimeError('本地服务退出：'+(results/'server.log').read_text(encoding='utf8')[-2000:])
                    time.sleep(.2)
                if url:break
                if proc.poll() is None:
                    proc.terminate();raise RuntimeError('服务启动超时，请查看 results/server.log')
            else:raise RuntimeError('没有可用的本机端口')
        (ROOT/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>倒立摆实验室</title><meta http-equiv="refresh" content="0;url='+url+'"><script>location.replace('+json.dumps(url)+');</script></html>',encoding='utf8')
        record.write_text(json.dumps(dict(url=url,pid=pid)),encoding='utf8');phase('实验室已就绪');return url
    finally:lock.close()

def main():
    os.chdir(ROOT);url=ensure_service()
    if '--no-open' not in sys.argv:open_browser(url,desktop='--desktop' in sys.argv)
    print(url,flush=True);return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as error:
        (ROOT/'results').mkdir(exist_ok=True);(ROOT/'results/启动.log').write_text(traceback.format_exc(),encoding='utf8')
        print(str(error),file=sys.stderr);sys.exit(1)
