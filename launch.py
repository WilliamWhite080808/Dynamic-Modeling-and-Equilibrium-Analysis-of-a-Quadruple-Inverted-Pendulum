"""Double-click launcher: start the local service, then open the working URL."""
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import os

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:8765'

def healthy():
    try:
        with urllib.request.urlopen(URL+'/api/health',timeout=1) as response:
            return response.status==200
    except Exception:return False

def main():
    if not healthy():
        (ROOT/'results').mkdir(exist_ok=True)
        with open(ROOT/'results'/'server.log','a',encoding='utf8') as log:
            flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
            subprocess.Popen([sys.executable,'-m','triple_pendulum.server'],cwd=ROOT,stdout=log,stderr=log,creationflags=flags)
        for _ in range(60):
            if healthy():break
            time.sleep(.25)
        else:
            print('启动失败，请查看 results/server.log 并安装 requirements.txt 中的依赖。')
            return 1
    print('实验室已就绪：'+URL)
    webbrowser.open(URL)
    return 0

if __name__=='__main__':sys.exit(main())
