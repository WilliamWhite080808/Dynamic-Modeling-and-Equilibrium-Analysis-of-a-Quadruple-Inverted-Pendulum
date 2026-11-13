"""Opt-in, isolated headless-Firefox acceptance of the exact extracted HTML.

Uses Mozilla's official marionette_driver test client; never attaches to a user
browser or profile. This test dependency is not part of the distribution.
"""
from pathlib import Path
import base64,gzip,hashlib,json,re,socket,subprocess,sys,time,uuid,zipfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'results/portable-qa-python'))
from marionette_driver.marionette import Marionette
from marionette_driver.by import By

QA=ROOT/'results/portable-acceptance'
QA.mkdir(parents=True,exist_ok=True)

def main():
    recipient=QA/('recipient '+uuid.uuid4().hex[:8]);recipient.mkdir()
    archive=ROOT/'dist/前四阶倒立摆_离线分享包.zip'
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():assert (recipient/member.filename).resolve().is_relative_to(recipient.resolve())
        bundle.extractall(recipient)
    page=next(recipient.rglob('*.html'))
    text=page.read_text(encoding='utf8')
    data=json.loads(re.search(r'<script id="portable-data" type="application/json">(.*?)</script>',text,re.S).group(1))
    assert len(data['catalog'])==310
    fixtures=[]
    designs=json.loads(gzip.decompress(base64.b64decode(data['designs'])))
    for row in data['catalog']:
        key=f"{row['order']}-{row['source']}-{row['target']}"
        raw=gzip.decompress(base64.b64decode(data['plans'][key]));assert hashlib.sha256(raw).hexdigest()==row['sha256']
        fixtures.append(dict(plan=json.loads(raw),design=designs[f"{row['order']}-{row['target']}-full_state"],source_design=designs[f"{row['order']}-{row['source']}-full_state"]))
    (QA/'worker-fixtures.json').write_text(json.dumps(fixtures),encoding='utf8')
    for name in ('physics.js','sim-worker.js','experiment.js'):
        assert data['modules'][name]==(ROOT/'web'/name).read_text(encoding='utf8'),name
    print('PASS embedded 310 original plan hashes and identical physical Worker modules',flush=True)
    profile=QA/('profile-'+uuid.uuid4().hex[:8]);profile.mkdir();downloads=QA/'downloads';downloads.mkdir(exist_ok=True)
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    preferences={
        'marionette.port':port,'browser.shell.checkDefaultBrowser':False,'browser.aboutwelcome.enabled':False,
        'browser.startup.homepage_override.mstone':'ignore','browser.startup.homepage':'about:blank',
        'network.proxy.type':1,'network.proxy.http':'127.0.0.1','network.proxy.http_port':9,
        'network.proxy.ssl':'127.0.0.1','network.proxy.ssl_port':9,'network.proxy.no_proxies_on':'',
        'browser.download.folderList':2,'browser.download.dir':str(downloads),'browser.download.useDownloadDir':True,
        'browser.helperApps.neverAsk.saveToDisk':'video/webm,video/mp4,application/json,text/csv,application/octet-stream',
    }
    (profile/'user.js').write_text('\n'.join(f'user_pref({json.dumps(key)}, {json.dumps(value)});' for key,value in preferences.items()),encoding='utf8')
    log=(QA/'firefox.log').open('w',encoding='utf8')
    browser=subprocess.Popen(['C:/Program Files/Mozilla Firefox/firefox.exe','--headless','--no-remote','--marionette','--profile',str(profile),'about:blank'],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    driver=Marionette(port=port,startup_timeout=45,socket_timeout=60)
    checks=[]
    def js(source,*args):return driver.execute_script(source,script_args=list(args),sandbox=None)
    def wait(condition,timeout=25):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=js(condition)
            if value:return value
            time.sleep(.1)
        raise AssertionError('Timed out: '+condition+'\n'+str(js("return {notice:document.querySelector('#notice')?.textContent,start:document.querySelector('#portable-start')?.textContent,status:document.querySelector('#status')?.textContent};")))
    def click(selector):driver.find_element(By.CSS_SELECTOR,selector).click()
    def screenshot(name,full=False):
        path=QA/name;path.write_bytes(base64.b64decode(driver.screenshot(full=full)));return str(path)
    try:
        driver.start_session();driver.set_window_rect(width=1680,height=1200)
        driver.navigate(page.as_uri()+'?order=4')
        wait("return !document.querySelector('#portable-start') && document.querySelector('#transfer-count').textContent==='240/240';",60)
        assert js("return location.protocol")=='file:'
        assert js("return document.querySelectorAll('#orders button').length")==4
        assert js("return document.querySelectorAll('#transfer-from-options button').length")==16
        assert js("return document.querySelectorAll('#transfer-to-options button').length")==16
        assert not js("return /播放|暂停|巡游|FPS/.test(document.body.innerText)")
        checks.append('file URL starts with dead network proxy; all 16+16 fourth-order poses visible; 240/240 ready')
        print('PASS direct file:// boot, no server or network, complete fourth-order pose selectors',flush=True)
        # Keep real UI interactions and the actual Worker. DOM inputs dispatch
        # their ordinary events; no state/physics/reference values are edited.
        click('#speed-toggle')
        driver.execute_script("const input=document.querySelector('#speed');input.value='10';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));",sandbox=None)
        click('#speed-toggle')
        wait("return document.querySelector('#speed-label').textContent.includes('10');")
        for order,count in [(1,2),(2,12),(3,56),(4,240)]:
            click(f'#orders [data-order="{order}"]')
            wait(f"return document.querySelector('#transfer-count').textContent==='{count}/{count}' && document.querySelector('#status').textContent==='已稳定';",35)
            checks.append(f'{order}-link default hanging swing-up reaches stable state')
            print('PASS order',order,'stable',flush=True)
        # Choose a folded final configuration that visibly crosses the cart.
        click('#transfer-to-options [data-pose="DUUD"]')
        # An explicit stop during asynchronous decompression/loading must win.
        click('#pause')
        wait("return document.querySelector('#pause').textContent==='继续摆动' && document.querySelector('#transfer-note').textContent.includes('↓↓↓↓ → ↓↑↑↓');")
        time.sleep(.3)
        assert js("return document.querySelector('#pause').textContent")=='继续摆动'
        driver.execute_script("const input=document.querySelector('#experiment-seek');input.value=input.max/2;input.dispatchEvent(new Event('pointerdown',{bubbles:true}));input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));",sandbox=None)
        time.sleep(.5)
        half=js("return {clock:document.querySelector('#clock').textContent,progress:document.querySelector('#experiment-time').textContent};")
        assert abs(float(half['clock'].split(':')[1])-float(half['progress'].split('/')[1].split()[0])/2)<.03,half
        driver.execute_script("const input=document.querySelector('#experiment-seek');input.value=input.max;input.dispatchEvent(new Event('pointerdown',{bubbles:true}));input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));",sandbox=None)
        wait("return document.querySelector('#status').textContent==='已停止摆动' && parseFloat(document.querySelector('#stable-metric').textContent)>.35;")
        assert js("return document.querySelector('#pause').textContent")=='继续摆动'
        checks.append('selection starts automatically; stopped timeline seeks to middle and certified endpoint +0.5 s')
        print('PASS selection and physical timeline seek',half,flush=True)
        # Check every compressed record through the browser's actual lazy loader.
        result=driver.execute_async_script("""const done=arguments[arguments.length-1];(async()=>{let count=0;for(const row of globalThis.PENDULUM_OFFLINE.manifest.files){const [n,a,b]=row.key.split('-');const plan=await globalThis.PENDULUM_OFFLINE.loadPlan(Number(n),a,b);if(plan.transition.source!==a||plan.transition.target!==b)throw Error(row.key);count++;}done({count});})().catch(e=>done({error:e.message}));""",sandbox=None,script_timeout=60000)
        assert result.get('count')==310,result;checks.append('all 310 records load and pass SHA-256 validation inside file-origin browser')
        js('window.scrollTo(0,0);return true;')
        screenshot('offline-interface.png',full=True)
        js("document.querySelector('#experiment-seek').scrollIntoView({block:'end'});return true;")
        screenshot('offline-controls.png')
        frozen=js("return document.querySelector('#clock').textContent;")
        time.sleep(.25)
        assert js("return document.querySelector('#clock').textContent;")==frozen
        click('#pause')
        wait("return document.querySelector('#pause').textContent==='停止摆动' && document.querySelector('#clock').textContent!==arguments[0];".replace('arguments[0]',json.dumps(frozen)))
        click('#pause');wait("return document.querySelector('#pause').textContent==='继续摆动';")
        click('#speed-toggle')
        js("const input=document.querySelector('#speed-range');input.value='.1';input.dispatchEvent(new Event('input',{bubbles:true}));return true;")
        assert js("return document.querySelector('#speed').value;")=='0.1'
        js("const input=document.querySelector('#speed');input.value='1.234';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));return true;")
        assert js("return document.querySelector('#speed-range').value;")=='1.234'
        js("const input=document.querySelector('#speed');input.value='10';input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));return true;")
        click('#speed-toggle');checks.append('stop freezes clock, resume advances it, 0.1x slider and manual fractional speed work')
        click('#open-inventory')
        wait("return document.querySelectorAll('#inventory-cards .initial-card').length===16;")
        screenshot('offline-warehouse.png')
        click('#inventory-cards [data-card="0"]')
        click('#inventory-targets [data-target="UUUU"]')
        click('#inventory-play')
        wait("return !document.querySelector('#inventory-dialog').open && document.querySelector('#status').textContent==='已稳定';",35)
        checks.append('16 warehouse initial cards show angle/angular velocity and execute selected transition')
        # Hold for 10 simulated seconds before an automatic trajectory restart.
        last=js("return document.querySelector('#clock').textContent;")
        restarted=False;deadline=time.monotonic()+18
        def seconds(value):
            minute,second=value.split(':');return int(minute)*60+float(second)
        while time.monotonic()<deadline:
            current=js("return document.querySelector('#clock').textContent;")
            if seconds(current)<seconds(last)-1:restarted=True;break
            last=current;time.sleep(.08)
        assert restarted,'Automatic stable-hold loop did not restart'
        checks.append('stable-hold loop automatically restarts using real integration')
        click('#transfer-cruise')
        wait("return /结束序列 [1-9]/.test(document.querySelector('#transfer-cruise').textContent);",35)
        click('#transfer-cruise');checks.append('continuous sequence advances to next edge')
        # A short genuine canvas-only capture must yield a nonempty local file.
        click('#record-core');time.sleep(2)
        click('#record-core')
        wait("return !document.querySelector('.record-download').classList.contains('hidden');")
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and not list(downloads.glob('*.webm')) and not list(downloads.glob('*.mp4')):time.sleep(.15)
        videos=list(downloads.glob('*.webm'))+list(downloads.glob('*.mp4'));assert videos
        video=max(videos,key=lambda p:p.stat().st_mtime);assert video.stat().st_size>10000
        checks.append('core canvas recording exports an actual nonempty video file without a server')
        rate=driver.execute_async_script("const done=arguments[arguments.length-1],times=[];const begin=performance.now();function frame(t){times.push(t);if(t-begin<1000)requestAnimationFrame(frame);else done({frames:times.length,duration:t-begin});}requestAnimationFrame(frame);",sandbox=None,script_timeout=10000)
        report=dict(passed=True,checked_at=time.time(),browser=driver.session_capabilities,html=str(page),html_sha256=hashlib.sha256(page.read_bytes()).hexdigest(),checks=checks,core_video=str(video),core_video_bytes=video.stat().st_size,raf_sample=rate,network='isolated test profile routes HTTP/HTTPS through unavailable loopback proxy; file and embedded blob resources only')
        (QA/'browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print('BROWSER_PASS '+json.dumps(dict(checks=len(checks),core_video_bytes=video.stat().st_size,raf=rate)),flush=True)
    except BaseException:
        try:screenshot('failure.png')
        except Exception:pass
        raise
    finally:
        try:driver.delete_session()
        except Exception:pass
        browser.terminate();browser.wait(timeout=15);log.close()

if __name__=='__main__':main()
