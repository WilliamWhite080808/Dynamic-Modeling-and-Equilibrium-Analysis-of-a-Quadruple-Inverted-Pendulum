using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

internal sealed class CompactStart : Form {
    readonly string root=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"程序文件");
    readonly string[] args;
    readonly Label status=new Label();
    public CompactStart(string[] values) {
        args=values;Text="倒立摆实验室";ClientSize=new Size(480,130);StartPosition=FormStartPosition.CenterScreen;
        Font=new Font("Microsoft YaHei UI",11);BackColor=Color.FromArgb(245,248,253);
        status.Dock=DockStyle.Fill;status.TextAlign=ContentAlignment.MiddleCenter;status.Text="正在准备随包数值引擎…";Controls.Add(status);Shown+=Start;
    }
    static string Hash(string file) {using(var sha=SHA256.Create())using(var input=File.OpenRead(file))return BitConverter.ToString(sha.ComputeHash(input)).Replace("-","").ToLowerInvariant();}
    static string TextHash(string text) {using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(text))).Replace("-","").ToLowerInvariant();}
    static string Quote(string value) {
        var b=new StringBuilder("\"");int n=0;
        foreach(char c in value){if(c=='\\'){n++;continue;}b.Append('\\',c=='"'?2*n+1:n);b.Append(c);n=0;}
        b.Append('\\',2*n);b.Append('"');return b.ToString();
    }
    async void Start(object sender,EventArgs e) {
        try {await Task.Run(new Action(Prepare));Close();}
        catch(Exception error){status.Text="启动失败："+error.Message;Environment.ExitCode=1;}
    }
    void Prepare() {
        var bundle=Path.Combine(root,"runtime.7z");var extractor=Path.Combine(root,"7zr.exe");
        var lines=File.ReadAllLines(Path.Combine(root,"runtime.sha256"));
        if(lines.Length!=2||Hash(bundle)!=lines[0].Trim()||Hash(extractor)!=lines[1].Trim())throw new Exception("随包引擎校验失败，请重新完整解压。");
        var cacheBase=Environment.GetEnvironmentVariable("PENDULUM_TEST_CACHE_ROOT");
        if(String.IsNullOrEmpty(cacheBase))cacheBase=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"PendulumLab","Cache");
        var home=Path.Combine(cacheBase,"runtime-"+lines[0].Trim());Directory.CreateDirectory(home);
        var runtime=Path.Combine(home,"runtime");var ready=Path.Combine(home,"ready.txt");
        using(var gate=new Mutex(false,"Local\\PendulumRuntime-"+lines[0].Trim())) {
            bool held=false;
            try {
                try{held=gate.WaitOne(180000);}catch(AbandonedMutexException){held=true;}
                if(!held)throw new Exception("另一个窗口仍在展开数值引擎，请稍后重试。");
                if(!File.Exists(ready)||!File.Exists(Path.Combine(runtime,"python.exe"))) {
                    var unpack=new ProcessStartInfo(extractor,"x "+Quote(bundle)+" -o"+Quote(home)+" -y -bsp0 -bso0");
                    unpack.UseShellExecute=false;unpack.CreateNoWindow=true;unpack.WindowStyle=ProcessWindowStyle.Hidden;
                    using(var process=Process.Start(unpack)){process.WaitForExit();if(process.ExitCode!=0)throw new Exception("数值引擎展开失败。");}
                    if(!File.Exists(Path.Combine(runtime,"python.exe")))throw new Exception("随包引擎缺少Python。");
                    File.WriteAllText(ready,lines[0].Trim(),Encoding.ASCII);
                }
            }finally{if(held)gate.ReleaseMutex();}
        }
        var state=Path.Combine(cacheBase,"app-"+TextHash(root.ToUpperInvariant()));Directory.CreateDirectory(state);
        var command=new StringBuilder();foreach(var arg in args){if(command.Length>0)command.Append(' ');command.Append(Quote(arg));}
        var start=new ProcessStartInfo(Path.Combine(root,"界面.exe"),command.ToString());start.WorkingDirectory=root;
        start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
        start.EnvironmentVariables["PENDULUM_RUNTIME_HOME"]=runtime;start.EnvironmentVariables["PENDULUM_CACHE_HOME"]=state;
        start.EnvironmentVariables["OPENBLAS_NUM_THREADS"]="1";start.EnvironmentVariables["MKL_NUM_THREADS"]="1";start.EnvironmentVariables["OMP_NUM_THREADS"]="1";
        start.EnvironmentVariables["OPENBLAS_CORETYPE"]="NEHALEM";start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]="1";
        start.EnvironmentVariables["NPY_DISABLE_CPU_FEATURES"]="SSSE3,SSE41,POPCNT,SSE42,AVX,F16C,FMA3,AVX2,AVX512F,AVX512CD,AVX512_SKX,AVX512_CLX,AVX512_CNL,AVX512_ICL";
        start.EnvironmentVariables["PYTHONPYCACHEPREFIX"]=Path.Combine(state,"pycache");
        using(var host=Process.Start(start)) {if(args.Length>0){host.WaitForExit();Environment.ExitCode=host.ExitCode;}}
    }
    [STAThread]
    static void Main(string[] args){Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new CompactStart(args));}
}
