using System.Windows;

namespace VPNSL.Windows;

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        BootstrapLog.Write($"Program.Main entered; pid={Environment.ProcessId}; exe={Environment.ProcessPath}; base={AppContext.BaseDirectory}");

        if (args.Any(arg => string.Equals(arg, "--startup-smoke-test", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                var marker = Environment.GetEnvironmentVariable("VPNSL_STARTUP_SMOKE_MARKER");
                if (string.IsNullOrWhiteSpace(marker))
                    marker = Path.Combine(Path.GetTempPath(), "VPNSL-startup-smoke-test.ok");

                var directory = Path.GetDirectoryName(marker);
                if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
                File.WriteAllText(marker, $"VPNSL startup smoke test OK {DateTimeOffset.Now:O}{Environment.NewLine}");
                BootstrapLog.Write($"Startup smoke test succeeded; marker={marker}");
                return 0;
            }
            catch (Exception ex)
            {
                BootstrapLog.Write("Startup smoke test failed: " + ex);
                return 2;
            }
        }

        try
        {
            BootstrapLog.Write("Creating WPF App instance.");
            var app = new App();

            BootstrapLog.Write("Loading App.xaml resources.");
            app.InitializeComponent();

            BootstrapLog.Write("Entering WPF dispatcher.");
            return app.Run();
        }
        catch (Exception ex)
        {
            BootstrapLog.Write("FATAL before/during WPF startup: " + ex);
            try
            {
                MessageBox.Show(
                    "VPNSL не удалось запустить.\n\n" + ex.Message +
                    "\n\nДиагностика записана в:\n%TEMP%\\VPNSL-startup.log\n%APPDATA%\\VPNSL\\startup.log",
                    "VPNSL — критическая ошибка запуска",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
            catch
            {
            }

            return 1;
        }
    }
}

internal static class BootstrapLog
{
    private static readonly object Gate = new();

    public static void Write(string message)
    {
        var line = $"[{DateTimeOffset.Now:O}] {message}{Environment.NewLine}";
        lock (Gate)
        {
            TryAppend(Path.Combine(Path.GetTempPath(), "VPNSL-startup.log"), line);

            try
            {
                var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
                if (!string.IsNullOrWhiteSpace(appData))
                    TryAppend(Path.Combine(appData, "VPNSL", "startup.log"), line);
            }
            catch
            {
            }
        }
    }

    private static void TryAppend(string path, string text)
    {
        try
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
            File.AppendAllText(path, text);
        }
        catch
        {
        }
    }
}
