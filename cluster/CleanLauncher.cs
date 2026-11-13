using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

// The only public entry; implementation files stay in the adjacent resource folder.
internal static class CleanLauncher {
    static string Quote(string value) {
        var result=new StringBuilder("\"");int slashes=0;
        foreach(char c in value) {
            if(c=='\\'){slashes++;continue;}
            result.Append('\\',c=='"'?slashes*2+1:slashes);result.Append(c);slashes=0;
        }
        result.Append('\\',slashes*2);result.Append('"');return result.ToString();
    }
    [STAThread]
    static int Main(string[] args) {
        try {
            var home=AppDomain.CurrentDomain.BaseDirectory;
            var resources=Path.Combine(home,"程序文件");
            var name=Path.GetFileName(Process.GetCurrentProcess().MainModule.FileName);
            var target=Path.Combine(resources,name);
            if(!File.Exists(target))throw new Exception("请完整解压或复制整个文件夹，保留“程序文件”。");
            var command=new StringBuilder();
            foreach(var arg in args){if(command.Length>0)command.Append(' ');command.Append(Quote(arg));}
            var start=new ProcessStartInfo(target,command.ToString());
            start.WorkingDirectory=resources;start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
            using(var process=Process.Start(start)) {
                if(args.Length>0){process.WaitForExit();return process.ExitCode;}
            }
            return 0;
        }catch(Exception error){MessageBox.Show(error.Message,"倒立摆实验室",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
    }
}
