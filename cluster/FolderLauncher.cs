using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class FolderLauncher {
    [STAThread]
    private static void Main(string[] args) {
        var root = AppDomain.CurrentDomain.BaseDirectory;
        try {
            var python = Path.Combine(root, "runtime", "pythonw.exe");
            if (!File.Exists(python)) throw new Exception("请先完整解压文件夹，保留 runtime 目录。");
            var start = new ProcessStartInfo(python, "\"" + Path.Combine(root, "launch.py") + "\"" + (Array.IndexOf(args, "--no-open") >= 0 ? " --no-open" : ""));
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(start);
        } catch (Exception error) {
            MessageBox.Show(error.Message, "倒立摆实验室", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
