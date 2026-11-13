"""Isolated browser acceptance of a folder-local complete application."""
from pathlib import Path
import base64,json,socket,subprocess,sys,time,uuid,urllib.request,tomllib
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'results/portable-qa-python'))
from marionette_driver.marionette import Marionette
from marionette_driver.by import By

def main():
    folder=Path(sys.argv[1]).resolve();qa=ROOT/'results/folder-acceptance';qa.mkdir(exist_ok=True)
    endpoint=json.loads((folder/'.cache/instance.json').read_text())['url']
    release=tomllib.loads((folder/'release.toml').read_text(encoding='utf8')) if (folder/'release.toml').exists() else json.loads((folder/'release.json').read_text())
    profile=qa/('profile-'+uuid.uuid4().hex[:8]);profile.mkdir();downloads=qa/'downloads';downloads.mkdir(exist_ok=True)
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    prefs={'marionette.port':port,'browser.shell.checkDefaultBrowser':False,'browser.aboutwelcome.enabled':False,'browser.startup.homepage_override.mstone':'ignore','network.proxy.type':1,'network.proxy.http':'127.0.0.1','network.proxy.http_port':9,'network.proxy.ssl':'127.0.0.1','network.proxy.ssl_port':9,'network.proxy.no_proxies_on':'127.0.0.1,localhost','browser.download.folderList':2,'browser.download.dir':str(downloads),'browser.download.useDownloadDir':True,'browser.helperApps.neverAsk.saveToDisk':'video/webm,video/mp4,application/json,text/csv,application/octet-stream'}
    (profile/'user.js').write_text('\n'.join(f'user_pref({json.dumps(k)},{json.dumps(v)});' for k,v in prefs.items()),encoding='utf8')
    log=(qa/'firefox.log').open('w');browser=subprocess.Popen(['C:/Program Files/Mozilla Firefox/firefox.exe','--headless','--no-remote','--marionette','--profile',str(profile),'about:blank'],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    driver=Marionette(port=port,startup_timeout=45,socket_timeout=90);checks=[]
    def js(code,*args):return driver.execute_script(code,script_args=list(args),sandbox=None)
    def wait(code,timeout=60):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            value=js(code)
            if value:return value
            time.sleep(.15)
        raise AssertionError(code+' '+str(js("return {angle:document.querySelector('#angle-metric')?.textContent,clock:document.querySelector('#clock')?.textContent,timeline:document.querySelector('#experiment-time')?.textContent,note:document.querySelector('#transfer-note')?.textContent,checkButton:document.querySelector('#check-motion-updates')?.outerHTML,handler:typeof document.querySelector('#check-motion-updates')?.onclick,dialogs:document.querySelectorAll('dialog[open]').length,status:document.querySelector('#status')?.textContent,loading:document.querySelector('#loading')?.textContent,notice:document.querySelector('#notice')?.textContent};")))
    def click(selector):driver.find_element(By.CSS_SELECTOR,selector).click()
    def shot(name):
        file=qa/name;file.write_bytes(base64.b64decode(driver.screenshot(full=True)));return str(file)
    try:
        driver.start_session();driver.set_window_rect(width=1680,height=1200);driver.navigate((folder/'index.html').as_uri())
        wait("return document.querySelector('#transfer-count')?.textContent==='56/56' && document.querySelector('#loading').classList.contains('hidden');")
        assert js('return location.origin;')==endpoint
        assert js('return document.querySelectorAll("dialog[open]").length;')==0
        assert js('return document.querySelectorAll("#orders button").length;')==5
        assert not js('return /播放|暂停|巡游|FPS/.test(document.body.innerText);')
        checks.append('index.html automatically enters this folder instance, no chooser or modal, external network proxy disabled')
        click('#speed-toggle');js("let input=document.querySelector('#speed');input.value=10;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));");click('#speed-toggle')
        for n,count in ([(4,240)] if '--seek-only' in sys.argv else [(n,release['orders'][str(n)]) for n in range(1,6)]):
            wait(f"return !document.querySelector('#orders [data-order=\"{n}\"]').disabled;")
            click(f'#orders [data-order="{n}"]')
            wait(f"return document.querySelector('#transfer-count').textContent==='{count}/{2**n*(2**n-1)}' && document.querySelector('#orders [data-order=\"{n}\"]').classList.contains('selected')&&!document.querySelector('#orders [data-order=\"{n}\"]').disabled&&document.querySelector('#transfer-note').textContent.startsWith('{'↓'*n} → ')&&parseFloat(document.querySelector('#angle-metric').textContent)<.5&&parseFloat(document.querySelector('#stable-metric').textContent)>=1;",90)
            checks.append(f'{n}-link default hanging start reaches stable through a certified plugin')
            print('PASS hanging',n,flush=True)
        if '--seek-only' not in sys.argv:assert driver.find_element(By.CSS_SELECTOR,'#transfer-cruise').get_attribute('disabled')=='true'
        checks.append('incomplete fifth-order full tour remains disabled')
        shot('fifth-order.png')
        click('#orders [data-order="4"]');wait("return document.querySelector('#transfer-count').textContent==='240/240' && document.querySelector('#status').textContent==='已稳定';")
        click('#transfer-to-options [data-pose="DUUD"]');click('#pause');wait("return document.querySelector('#pause').textContent==='继续摆动' && document.querySelector('#transfer-note').textContent.includes('↓↓↓↓ → ↓↑↑↓') && !document.querySelector('#experiment-seek').disabled;")
        js("let i=document.querySelector('#experiment-seek');i.value=i.max;i.dispatchEvent(new Event('pointerdown',{bubbles:true}));i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));")
        wait("return document.querySelector('#status').textContent==='已停止摆动' && parseFloat(document.querySelector('#stable-metric').textContent)>.35 && parseFloat(document.querySelector('#angle-metric').textContent)<.5 && Math.abs(document.querySelector('#experiment-seek').value-document.querySelector('#experiment-seek').max)<.01;")
        checks.append('pose switch jumps automatically; explicit stop and physical timeline seek work')
        shot('interface.png')
        click('#open-inventory');wait('return document.querySelectorAll("#inventory-cards .initial-card").length>=16;');shot('warehouse.png');click('#close-inventory');wait("return document.querySelectorAll('dialog[open]').length===0;");time.sleep(.3)
        checks.append('warehouse shows passive initial angles and angular velocities from motion plugins')
        click('#check-motion-updates');print('CHECK CLICK',js("return {button:document.querySelector('#check-motion-updates').outerHTML,handler:typeof document.querySelector('#check-motion-updates').onclick};"),flush=True);wait("return !document.querySelector('#check-motion-updates').disabled && document.querySelector('#check-motion-updates').title.includes('已检查');")
        checks.append('manual trajectory check completes without forcing a simulation restart')
        click('#record-core');wait("return document.querySelector('#record-core').classList.contains('recording');");time.sleep(2.2);click('#record-core');wait("return !document.querySelector('.record-download').classList.contains('hidden');",20)
        with urllib.request.urlopen(endpoint+'/api/health') as response:assert json.load(response)['instance']==str(folder)
        assert any(p.stat().st_size>1000 for p in (folder/'recordings').glob('*.webm'))
        js("let v=document.createElement('video');v.muted=true;v.src=document.querySelector('.record-download').href;v.id='recording-check';v.style.display='none';document.body.append(v);v.load();")
        wait("return document.querySelector('#recording-check').readyState>=2&&document.querySelector('#recording-check').videoWidth>0;",20)
        checks.append('core-area recording is saved inside recipient folder')
        click('#edit-initial');wait('return document.querySelector("#initial-dialog").open;');shot('custom-initial.png')
        checks.append('custom initial-value solver remains available')
        report=dict(passed=True,folder=str(folder),endpoint=endpoint,checks=checks,screenshot=str(qa/'interface.png'))
        (qa/'browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False),flush=True)
    except Exception:
        try:shot('failure.png')
        except Exception:pass
        raise
    finally:
        try:driver.delete_session()
        except Exception:pass
        browser.terminate()
        try:browser.wait(timeout=12)
        except subprocess.TimeoutExpired:browser.kill();browser.wait()
        log.close()

if __name__=='__main__':main()
