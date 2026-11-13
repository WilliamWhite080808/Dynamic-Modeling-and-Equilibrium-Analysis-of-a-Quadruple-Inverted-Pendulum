using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class DesktopHost : Form {
    readonly string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
    readonly string testFolder;
    readonly Label status=new Label();
    readonly System.Windows.Forms.Timer progress=new System.Windows.Forms.Timer();
    readonly JavaScriptSerializer json=new JavaScriptSerializer();
    WebView2 view;
    string url;
    int servicePid;
    bool closing;
    bool preparing=true;
    string RuntimePython {get{return Path.Combine(Environment.GetEnvironmentVariable("PENDULUM_RUNTIME_HOME")??Path.Combine(root,"runtime"),"python.exe");}}
    string WindowCache {get{return Path.Combine(Environment.GetEnvironmentVariable("PENDULUM_CACHE_HOME")??Path.Combine(root,".cache"),"window");}}
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr handle);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr handle,int command);

    public DesktopHost(string test) {
        testFolder=test;
        Text="倒立摆实验室";ClientSize=new Size(1500,1000);MinimumSize=new Size(1000,700);
        StartPosition=FormStartPosition.CenterScreen;WindowState=FormWindowState.Maximized;BackColor=Color.FromArgb(244,247,252);
        AutoScaleMode=AutoScaleMode.Dpi;Font=new Font("Microsoft YaHei UI",11);
        status.Dock=DockStyle.Fill;status.TextAlign=ContentAlignment.MiddleCenter;
        status.Text="正在打开倒立摆实验室…\n载入预建轨迹索引";Controls.Add(status);
        progress.Interval=300;progress.Tick+=delegate {
            try {
                var p=Path.Combine(root,".cache","startup.txt");var t=Path.Combine(root,".cache","trajectory-progress.txt");
                if(File.Exists(p))status.Text=File.ReadAllText(p,Encoding.UTF8);
                if(File.Exists(t))status.Text+="\n"+File.ReadAllText(t,Encoding.UTF8);
            }catch(IOException){}
        };
        Shown+=Open;
        FormClosing+=delegate(object s,FormClosingEventArgs e) {
            closing=true;progress.Stop();
            // Let the launcher publish its PID before exiting; otherwise its
            // newly detached server can outlive an early window close.
            if(preparing){e.Cancel=true;Hide();}
        };
        FormClosed+=delegate {if(view!=null)view.Dispose();StopOwnService();};
    }

    async void Open(object sender,EventArgs args) {
        progress.Start();
        try {
            url=await Task.Run<string>(new Func<string>(Prepare));
            var instance=json.DeserializeObject(File.ReadAllText(Path.Combine(root,".cache","instance.json"),Encoding.UTF8)) as System.Collections.Generic.Dictionary<string,object>;
            if(instance.ContainsKey("pid")&&instance["pid"]!=null)servicePid=Convert.ToInt32(instance["pid"]);
            preparing=false;
            if(closing){StopOwnService();Close();return;}
            view=new WebView2();view.Dock=DockStyle.Fill;view.Visible=false;Controls.Add(view);
            var engine=Path.Combine(root,"engine");
            if(!File.Exists(Path.Combine(engine,"msedgewebview2.exe")))engine=null;
            bool browserOnly=Environment.GetEnvironmentVariable("PENDULUM_FORCE_BROWSER")=="1";
            if(engine==null&&!browserOnly) {
                try{CoreWebView2Environment.GetAvailableBrowserVersionString(null);}
                catch{browserOnly=true;}
            }
            if(browserOnly){await BrowserFallback();return;}
            var options=new CoreWebView2EnvironmentOptions();
            options.AdditionalBrowserArguments="--disable-background-networking --disable-component-update --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling";
            CoreWebView2Environment env=null;bool fallbackAfterFailure=false;
            try {
                env=await CoreWebView2Environment.CreateAsync(engine,WindowCache,options);
                await view.EnsureCoreWebView2Async(env);
            } catch {
                if(engine==null&&testFolder==null)fallbackAfterFailure=true;
                else throw;
            }
            if(fallbackAfterFailure){await BrowserFallback();return;}
            view.CoreWebView2.Settings.AreDefaultContextMenusEnabled=false;
            view.CoreWebView2.NavigationStarting+=delegate(object s,CoreWebView2NavigationStartingEventArgs e) {
                Uri target;
                if(Uri.TryCreate(e.Uri,UriKind.Absolute,out target)&&target.Scheme=="http"&&target.Host!="127.0.0.1")e.Cancel=true;
            };
            view.CoreWebView2.NavigationCompleted+=async delegate(object s,CoreWebView2NavigationCompletedEventArgs e) {
                if(closing)return;
                if(!e.IsSuccess){Fail(new Exception("页面载入失败："+e.WebErrorStatus));return;}
                progress.Stop();status.Visible=false;view.Visible=true;view.BringToFront();
                File.WriteAllText(Path.Combine(root,"results","桌面窗口.log"),DateTime.Now.ToString("s")+"\nVisible="+Visible+"\nURL="+url+"\nEngine="+view.CoreWebView2.Environment.BrowserVersionString,Encoding.UTF8);
                if(testFolder!=null) {
                    Exception problem=null;
                    try {await SelfTest();}catch(Exception error){problem=error;}
                    if(problem!=null){try{await Shot("desktop-failure.png");}catch(Exception){}Fail(problem);Environment.ExitCode=1;}
                    else Environment.ExitCode=0;
                    Close();
                }
            };
            if(testFolder!=null)view.CoreWebView2.DownloadStarting+=delegate(object s,CoreWebView2DownloadStartingEventArgs e){e.ResultFilePath=Path.Combine(testFolder,Path.GetFileName(e.ResultFilePath));e.Handled=true;};
            view.CoreWebView2.Navigate(url);
        }catch(Exception error){preparing=false;if(closing){StopOwnService();Close();return;}Fail(error);if(testFolder!=null){Environment.ExitCode=1;Close();}}
    }

    string Prepare() {
        var python=RuntimePython;
        if(!File.Exists(python))throw new Exception("求解环境缺失，请完整解压桌面版。");
        var start=new ProcessStartInfo(python,"\""+Path.Combine(root,"launch.py")+"\" --no-open");
        start.WorkingDirectory=root;start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
        start.RedirectStandardOutput=true;start.RedirectStandardError=true;start.StandardOutputEncoding=Encoding.UTF8;start.StandardErrorEncoding=Encoding.UTF8;
        using(var child=Process.Start(start)) {
            var output=child.StandardOutput.ReadToEnd();var error=child.StandardError.ReadToEnd();child.WaitForExit();
            if(child.ExitCode!=0)throw new Exception(error);
            var lines=output.Trim().Split('\n');var value=lines[lines.Length-1].Trim();
            if(!value.StartsWith("http://127.0.0.1:"))throw new Exception("本机服务没有返回有效地址。");
            return value;
        }
    }
    async Task BrowserFallback() {
        if(view!=null){Controls.Remove(view);view.Dispose();view=null;}
        var output=await Task.Run(delegate {
            var info=new ProcessStartInfo(RuntimePython,"\""+Path.Combine(root,"launch.py")+"\" --desktop");
            info.WorkingDirectory=root;info.UseShellExecute=false;info.CreateNoWindow=true;info.WindowStyle=ProcessWindowStyle.Hidden;
            info.RedirectStandardOutput=true;info.RedirectStandardError=true;info.StandardOutputEncoding=Encoding.UTF8;info.StandardErrorEncoding=Encoding.UTF8;
            using(var child=Process.Start(info)){var text=child.StandardOutput.ReadToEnd();var error=child.StandardError.ReadToEnd();child.WaitForExit();if(child.ExitCode!=0)throw new Exception(error);return text;}
        });
        File.WriteAllText(Path.Combine(root,"results","桌面入口.log"),"Existing browser fallback\n"+output,Encoding.UTF8);
        servicePid=0;progress.Stop();Close();
    }
    void Fail(Exception error) {
        progress.Stop();status.Visible=true;status.BringToFront();status.ForeColor=Color.Firebrick;
        status.Text="启动未完成\n"+error.Message;
        Directory.CreateDirectory(Path.Combine(root,"results"));File.WriteAllText(Path.Combine(root,"results","桌面错误.log"),error.ToString(),Encoding.UTF8);
        if(testFolder!=null){Directory.CreateDirectory(testFolder);File.WriteAllText(Path.Combine(testFolder,"desktop-error.txt"),error.ToString(),Encoding.UTF8);}
    }
    void StopOwnService() {
        if(servicePid<=0)return;
        try {
            using(var p=Process.GetProcessById(servicePid)) {
                if(String.Equals(p.MainModule.FileName,RuntimePython,StringComparison.OrdinalIgnoreCase))p.Kill();
            }
        }catch(ArgumentException){}catch(System.ComponentModel.Win32Exception){}catch(InvalidOperationException){}
    }

    Task<string> Js(string code){return view.CoreWebView2.ExecuteScriptAsync(code);}
    async Task Wait(string condition,int seconds) {
        var end=DateTime.UtcNow.AddSeconds(seconds);
        while(DateTime.UtcNow<end){if(await Js(condition)=="true")return;await Task.Delay(120);}
        var actual=await Js("JSON.stringify({status:document.querySelector('#status')?.textContent,notice:document.querySelector('#notice')?.textContent,angle:document.querySelector('#angle-metric')?.textContent,time:document.querySelector('#experiment-time')?.textContent})");
        throw new Exception("界面验收超时："+condition+" / "+actual);
    }
    async Task Shot(string name) {
        using(var stream=File.Create(Path.Combine(testFolder,name)))await view.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,stream);
    }
    async Task SelfTest() {
        Directory.CreateDirectory(testFolder);var log=Path.Combine(testFolder,"desktop-checks.txt");
        File.WriteAllText(log,"Native form Visible="+Visible+"\nURL="+url+"\nEngine="+view.CoreWebView2.Environment.BrowserVersionString+"\n",Encoding.UTF8);
        await Wait("!!document.querySelector('#loading')&&document.querySelector('#loading').classList.contains('hidden')&&document.querySelector('#transfer-count').textContent==='56/56'",90);
        File.AppendAllText(log,"Viewport="+await Js("JSON.stringify({width:innerWidth,height:innerHeight,dpi:devicePixelRatio})")+"\n",Encoding.UTF8);
        if(await Js("Number(document.querySelector('#speed').value)===1&&document.querySelector('#speed-label').textContent==='1×'")!="true")throw new Exception("初始倍率不是 1×");
        Text="自动验收中 · 倒立摆实验室";
        await Js("for(const type of ['pointerdown','pointerup','click','keydown','input','change'])window.addEventListener(type,e=>{if(e.isTrusted){e.preventDefault();e.stopImmediatePropagation();}},{capture:true});true");
        int probe=Array.IndexOf(Environment.GetCommandLineArgs(),"--record-probe");
        if(probe>=0){await Js(File.ReadAllText(Environment.GetCommandLineArgs()[probe+1],Encoding.UTF8));await Wait("window.__recordProbe?.done===true",45);File.AppendAllText(log,await Js("JSON.stringify(window.__recordProbe)")+"\n",Encoding.UTF8);return;}
        if(Array.IndexOf(Environment.GetCommandLineArgs(),"--smoke")>=0){await Task.Delay(500);await Js("document.querySelector('#simulation').scrollIntoView({block:'center'})");await Shot("desktop-window.png");File.AppendAllText(log,"PASS maximized visible native window\n",Encoding.UTF8);return;}
        if(await Js("document.querySelectorAll('dialog[open]').length===0")!="true")throw new Exception("启动出现额外选择弹窗");
        await Js("(()=>{let i=document.querySelector('#speed');i.value=1;i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));return true;})()");
        for(int n=1;n<=5;n++) {
            await Wait("!document.querySelector('#orders [data-order=\""+n+"\"]').disabled",30);
            await Js("document.querySelector('#orders [data-order=\""+n+"\"]').click()");
            await Wait("document.querySelector('#orders [data-order=\""+n+"\"]').classList.contains('selected')&&!document.querySelector('#orders [data-order=\""+n+"\"]').disabled&&document.querySelector('#transfer-note').textContent.startsWith('"+new string('↓',n)+" → ')&&parseFloat(document.querySelector('#angle-metric').textContent)<.5&&parseFloat(document.querySelector('#stable-metric').textContent)>=1&&document.querySelector('#loading').classList.contains('hidden')",90);
            File.AppendAllText(log,"PASS hanging "+n+"\n",Encoding.UTF8);
        }
        await Shot("desktop-fifth.png");
        await Js("document.querySelector('#orders [data-order=\"4\"]').click()");
        await Wait("document.querySelector('#transfer-count').textContent==='240/240'&&document.querySelector('#orders [data-order=\"4\"]').classList.contains('selected')&&!document.querySelector('#orders [data-order=\"4\"]').disabled&&document.querySelector('#transfer-note').textContent.startsWith('↓↓↓↓ → ')&&document.querySelector('#status').textContent==='已稳定'",60);
        await Js("document.querySelector('#transfer-to-options [data-pose=\"DUUD\"]').click();document.querySelector('#pause').click()");
        await Wait("!document.querySelector('#experiment-seek').disabled&&document.querySelector('#pause').textContent==='继续摆动'&&document.querySelector('#transfer-note').textContent.includes('↓↓↓↓ → ↓↑↑↓')",30);
        await Js("(()=>{let i=document.querySelector('#experiment-seek');i.value=i.max;i.dispatchEvent(new Event('pointerdown',{bubbles:true}));i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));return true;})()");
        await Wait("parseFloat(document.querySelector('#angle-metric').textContent)<.5&&parseFloat(document.querySelector('#stable-metric').textContent)>.35&&Math.abs(document.querySelector('#experiment-seek').value-document.querySelector('#experiment-seek').max)<.01",30);
        await Shot("desktop.png");File.AppendAllText(log,"PASS stop, seek and final angle\n",Encoding.UTF8);
        await Js("document.querySelector('#check-motion-updates').click()");
        await Wait("!document.querySelector('#check-motion-updates').disabled&&document.querySelector('#check-motion-updates').title.includes('已检查')",60);
        await Js("document.querySelector('#open-inventory').click()");await Wait("document.querySelectorAll('#inventory-cards .initial-card').length>=16",30);
        await Shot("desktop-warehouse.png");await Js("document.querySelector('#close-inventory').click()");
        await Js("document.querySelector('#record-core').click()");
        await Wait("document.querySelector('#record-core').classList.contains('recording')",10);
        await Task.Delay(2200);await Js("document.querySelector('#record-core').click()");
        await Wait("!document.querySelector('.record-download').classList.contains('hidden')",20);
        var recordings=Directory.GetFiles(Path.Combine(root,"recordings"),"*.webm");
        if(recordings.Length==0||new FileInfo(recordings[recordings.Length-1]).Length<1000)throw new Exception("未生成有效核心区域录制文件");
        await Js("(()=>{let v=document.createElement('video');v.muted=true;v.src=document.querySelector('.record-download').href;v.id='recording-check';v.style.display='none';document.body.append(v);v.load();return true;})()");
        await Wait("document.querySelector('#recording-check').readyState>=2&&document.querySelector('#recording-check').videoWidth>0",20);
        File.AppendAllText(log,"PASS manual update, warehouse and core recording\nPASS native desktop using available WebView2 engine\n",Encoding.UTF8);
    }

    [STAThread] static void Main(string[] args) {
        try {Run(args);}
        catch(Exception error){Environment.ExitCode=1;MessageBox.Show("无法启动："+error.Message+"\n请确认整个文件夹已解压，并放在可写目录。","倒立摆实验室",MessageBoxButtons.OK,MessageBoxIcon.Error);}
    }
    static void Run(string[] args) {
        SetProcessDPIAware();Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        var root=AppDomain.CurrentDomain.BaseDirectory;string id;
        using(var sha=SHA256.Create())id=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(root.ToLowerInvariant()))).Replace("-","").Substring(0,20);
        bool created;
        using(var mutex=new Mutex(true,"Local\\PendulumDesktop"+id,out created)) {
            var pidFile=Path.Combine(root,".cache","desktop.pid");
            if(!created) {
                try {var p=Process.GetProcessById(Int32.Parse(File.ReadAllText(pidFile)));ShowWindow(p.MainWindowHandle,9);SetForegroundWindow(p.MainWindowHandle);}catch(Exception){}
                return;
            }
            Directory.CreateDirectory(Path.Combine(root,".cache"));File.WriteAllText(pidFile,Process.GetCurrentProcess().Id.ToString());
            string test=null;int index=Array.IndexOf(args,"--self-test");if(index>=0&&args.Length>index+1)test=args[index+1];
            Application.Run(new DesktopHost(test));mutex.ReleaseMutex();
        }
    }
}
