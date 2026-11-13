using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

internal sealed class WebStart : Form {
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly bool prepare;
    readonly Label status = new Label();
    readonly Timer timer = new Timer();
    public WebStart(bool noOpen) {
        prepare = noOpen;
        Text = "倒立摆实验室 · 网页版";
        ClientSize = new Size(510,170); StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(245,248,253); Font = new Font("Microsoft YaHei UI",11);
        status.Dock=DockStyle.Fill;status.TextAlign=ContentAlignment.MiddleCenter;
        status.Text="正在启动实验室…";Controls.Add(status);
        timer.Interval=300;timer.Tick+=delegate {
            try {
                var state=Path.Combine(root,".cache","startup.txt");
                var progress=Path.Combine(root,".cache","trajectory-progress.txt");
                if(File.Exists(state))status.Text=File.ReadAllText(state,Encoding.UTF8);
                if(File.Exists(progress))status.Text+="\n"+File.ReadAllText(progress,Encoding.UTF8);
            }catch(IOException){}
        };
        Shown+=Start;
    }
    async void Start(object sender,EventArgs args) {
        timer.Start();
        try {
            var result=await Task.Run(delegate {
                var python=Path.Combine(root,"runtime","python.exe");
                if(!File.Exists(python))throw new Exception("请完整解压文件夹，保留 runtime 目录。");
                var info=new ProcessStartInfo(python,"\""+Path.Combine(root,"launch.py")+"\""+(prepare?" --no-open":""));
                info.WorkingDirectory=root;info.UseShellExecute=false;info.CreateNoWindow=true;info.WindowStyle=ProcessWindowStyle.Hidden;
                info.RedirectStandardOutput=true;info.RedirectStandardError=true;
                info.StandardOutputEncoding=Encoding.UTF8;info.StandardErrorEncoding=Encoding.UTF8;
                using(var process=Process.Start(info)) {
                    var output=process.StandardOutput.ReadToEnd();var error=process.StandardError.ReadToEnd();process.WaitForExit();
                    if(process.ExitCode!=0)throw new Exception(error.Length>0?error:"启动失败，请查看 results/启动.log");
                    return output;
                }
            });
            timer.Stop();Directory.CreateDirectory(Path.Combine(root,"results"));
            File.WriteAllText(Path.Combine(root,"results","入口.log"),DateTime.Now.ToString("s")+"\n"+result,Encoding.UTF8);
            Close();
        }catch(Exception error) {
            timer.Stop();Environment.ExitCode=1;status.ForeColor=Color.Firebrick;
            status.Text="启动未完成\n"+error.Message;status.Font=new Font(Font.FontFamily,9);
            var copy=new Button {Text="复制错误",Dock=DockStyle.Bottom,Height=35};copy.Click+=delegate {Clipboard.SetText(error.ToString());};Controls.Add(copy);
            Directory.CreateDirectory(Path.Combine(root,"results"));File.WriteAllText(Path.Combine(root,"results","入口错误.log"),error.ToString(),Encoding.UTF8);
            if(prepare)Close();
        }
    }
    [STAThread] static void Main(string[] args) {
        try {
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new WebStart(Array.IndexOf(args,"--no-open")>=0));
        }catch(Exception error){Environment.ExitCode=1;MessageBox.Show("无法启动："+error.Message,"倒立摆实验室",MessageBoxButtons.OK,MessageBoxIcon.Error);}
    }
}
