"""Launch the real web EXE, with broken system Edge association and own Firefox profile."""
from pathlib import Path
import base64,json,os,socket,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'results/portable-qa-python'))
from marionette_driver.marionette import Marionette
from marionette_driver.by import By

def main():
    folder=Path(sys.argv[1]).resolve();qa=Path(sys.argv[sys.argv.index('--qa')+1]).resolve() if '--qa' in sys.argv else ROOT/'results/acceptance/web-entry';qa.mkdir(parents=True,exist_ok=True)
    resources=folder/'程序文件' if (folder/'程序文件').is_dir() else folder
    profile=qa/('web-profile-'+str(time.time_ns()));profile.mkdir()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    prefs={'marionette.port':port,'browser.shell.checkDefaultBrowser':False,'browser.aboutwelcome.enabled':False,'browser.startup.homepage_override.mstone':'ignore','network.proxy.type':1,'network.proxy.http':'127.0.0.1','network.proxy.http_port':9,'network.proxy.ssl':'127.0.0.1','network.proxy.ssl_port':9,'network.proxy.no_proxies_on':'127.0.0.1,localhost','widget.windows.window_occlusion_tracking.enabled':False,'dom.timeout.enable_budget_timer_throttling':False}
    (profile/'user.js').write_text('\n'.join(f'user_pref({json.dumps(k)},{json.dumps(v)});' for k,v in prefs.items()),encoding='utf8')
    env=os.environ.copy();env.update(PATH=os.environ['SystemRoot']+'\\System32',PYTHONHOME='Z:/missing-python',PYTHONPATH='Z:/missing-python',BROWSER='Z:/missing-edge.exe',PENDULUM_TEST_FIREFOX_PROFILE=str(profile),PYTHONUTF8='1')
    entry=sys.argv[sys.argv.index('--entry')+1] if '--entry' in sys.argv else '打开网页版.exe'
    if '--force-browser' in sys.argv:env['PENDULUM_FORCE_BROWSER']='1'
    opened_at=time.monotonic();app=subprocess.Popen([str(folder/entry)],cwd=folder,env=env,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_BREAKAWAY_FROM_JOB)
    driver=Marionette(port=port,startup_timeout=300,socket_timeout=90)
    def js(code):return driver.execute_script(code,sandbox=None)
    def wait(code,seconds=90):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if js(code):return
            time.sleep(.12)
        raise AssertionError(code+' '+str(js("return {url:location.href,status:document.querySelector('#status')?.textContent,notice:document.querySelector('#notice')?.textContent};")))
    try:
        driver.start_session();driver.set_window_rect(width=1680,height=1200)
        # Do not navigate: the EXE must have opened this page itself.
        wait("return location.origin.startsWith('http://127.0.0.1:')&&document.querySelector('#transfer-count')?.textContent==='56/56'&&document.querySelector('#loading').classList.contains('hidden');")
        endpoint=json.loads((resources/'.cache/instance.json').read_text())['url'];assert js('return location.origin;')==endpoint
        startup_seconds=time.monotonic()-opened_at
        assert js("return Number(document.querySelector('#speed').value)===1&&document.querySelector('#speed-label').textContent==='1×';")
        js("let i=document.querySelector('#speed');i.value=10;i.dispatchEvent(new Event('change',{bubbles:true}));return true;")
        driver.refresh()
        wait("return document.querySelector('#loading').classList.contains('hidden')&&Number(document.querySelector('#speed').value)===1&&document.querySelector('#speed-label').textContent==='1×';")
        (qa/'startup-1x.png').write_bytes(base64.b64decode(driver.screenshot(full=True)))
        chosen=(resources/'.cache/browser.txt').read_text(encoding='utf8');assert Path(chosen).name.lower()=='firefox.exe'
        wait("return document.querySelectorAll('dialog[open]').length===0;")
        assert js("let order=document.querySelector('.experiment-bar').getBoundingClientRect(),stage=document.querySelector('.stage-grid').getBoundingClientRect(),poses=document.querySelector('.transition-section').getBoundingClientRect();return order.bottom<=stage.top&&poses.top>=stage.bottom&&document.querySelector('#transfer-panel').closest('.transition-section')!==null;")
        assert js("return ['一阶摆','二阶摆','三阶摆','四阶摆','五阶摆'].every((label,i)=>document.querySelector('#orders [data-order=\"'+(i+1)+'\"]').textContent===label)&&document.querySelector('#open-routes').closest('.experiment-bar')!==null;")
        driver.find_element(By.CSS_SELECTOR,'#speed-toggle').click()
        js("let i=document.querySelector('#speed');i.value=10;i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));return true;")
        driver.find_element(By.CSS_SELECTOR,'#speed-toggle').click()
        for n in range(1,6):
            wait(f"return !document.querySelector('#orders [data-order=\"{n}\"]').disabled;")
            driver.find_element(By.CSS_SELECTOR,f'#orders [data-order="{n}"]').click()
            source='↓'*n
            wait(f"return document.querySelector('#transfer-note').textContent.startsWith('{source} → ')&&document.querySelector('#orders [data-order=\"{n}\"]').classList.contains('selected')&&!document.querySelector('#orders [data-order=\"{n}\"]').disabled&&parseFloat(document.querySelector('#angle-metric').textContent)<.5&&parseFloat(document.querySelector('#stable-metric').textContent)>=1;")
            print('WEB PASS hanging',n,flush=True)
        (qa/'web.png').write_bytes(base64.b64decode(driver.screenshot(full=True)))
        wait("return !document.querySelector('#orders [data-order=\"4\"]').disabled;")
        driver.find_element(By.CSS_SELECTOR,'#orders [data-order="4"]').click()
        wait("return document.querySelector('#transfer-count').textContent==='240/240'&&!document.querySelector('#orders [data-order=\"4\"]').disabled;")
        driver.find_element(By.CSS_SELECTOR,'#transfer-to-options [data-pose="DUUD"]').click()
        driver.find_element(By.CSS_SELECTOR,'#pause').click()
        wait("return document.querySelector('#transfer-note').textContent.includes('↓↓↓↓ → ↓↑↑↓')&&document.querySelector('#pause').textContent==='继续摆动'&&!document.querySelector('#experiment-seek').disabled;")
        report=dict(passed=True,entry=str(folder/entry),browser=chosen,url=endpoint,real_exe_opened_page_without_driver_navigation=True,orders_tested=[1,2,3,4,5],proxy_isolated=True,order_above_scene=True,poses_below_scene=True,lower_pose_real_pointer_click=True,default_speed=1,refresh_resets_speed_to_one=True,startup_seconds=startup_seconds)
        (qa/'web-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False),flush=True)
        app.wait(timeout=20);assert app.returncode==0
    finally:
        try:driver.quit()
        except Exception:
            try:driver.delete_session()
            except Exception:pass
        if app.poll() is None:app.terminate()

if __name__=='__main__':main()
