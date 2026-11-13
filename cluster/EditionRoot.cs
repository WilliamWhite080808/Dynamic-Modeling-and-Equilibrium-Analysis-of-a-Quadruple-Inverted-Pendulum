using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
internal static class EditionRoot {
    [STAThread] static void Main() {
        try {
            var folder=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"桌面版");
            var exe=Path.Combine(folder,"倒立摆.exe");
            if(!File.Exists(exe))throw new Exception("桌面版文件不完整，请完整解压桌面版压缩包。");
            Process.Start(new ProcessStartInfo(exe){WorkingDirectory=folder,UseShellExecute=false});
        }catch(Exception error){MessageBox.Show(error.Message,"倒立摆实验室",MessageBoxButtons.OK,MessageBoxIcon.Error);}
    }
}
