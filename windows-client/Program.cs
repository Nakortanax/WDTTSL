using System.Windows;

namespace VPNSL.Windows;

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        BootstrapLog.Write($"Program.Main entered; pid={Environment.ProcessId}; exe={Environment.ProcessPath}; base={AppContext.BaseDirectory}");

        if (HasArgument(args, "--startup-smoke-test"))
            return RunBasicSmokeTest();

        if (HasArgument(args, "--wpf-smoke-test"))
            return RunWpfSmokeTest();

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
            TryShowFatalMessage(ex);
            return 1;
        }
    }

    private static int RunBasicSmokeTest()
    {
        try
        {
            var marker = WriteSmokeMarker("VPNSL basic startup smoke test OK");
            BootstrapLog.Write($"Basic startup smoke test succeeded; marker={marker}");
            return 0;
        }
        catch (Exception ex)
        {
            BootstrapLog.Write("Basic startup smoke test failed: " + ex);
            return 2;
        }
    }

    private static int RunWpfSmokeTest()
    {
        try
        {
            BootstrapLog.Write("WPF smoke test: creating App.");
            var app = new App();

            BootstrapLog.Write("WPF smoke test: loading App.xaml.");
            app.InitializeComponent();

            BootstrapLog.Write("WPF smoke test: constructing MainWindow and loading MainWindow.xaml.");
            var window = new MainWindow();
            GC.KeepAlive(window);

            var marker = WriteSmokeMarker("VPNSL WPF/XAML startup smoke test OK");
            BootstrapLog.Write($"WPF/XAML smoke test succeeded; marker={marker}");
            return 0;
        }
        catch (Exception ex)
        {
            BootstrapLog.Write("WPF/XAML smoke test failed: " + ex);
            return 3;
        }
    }

    private static bool HasArgument(IEnumerable<string> args, string value) =>
        args.Any(arg => string.Equals(arg, value, StringComparison.OrdinalIgnoreCase));

    private static string WriteSmokeMarker(string text)
    {
        var marker = Environment.GetEnvironmentVariable("VPNSL_STARTUP_SMOKE_MARKER");
        if (string.IsNullOrWhiteSpace(marker))
            marker = Path.Combine(Path.GetTempPath(), "VPNSL-startup-smoke-test.ok");

        var directory = Path.GetDirectoryName(marker);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        File.WriteAllText(marker, $"{text} {DateTimeOffset.Now:O}{Environment.NewLine}");
        return marker;
    }

    private static void TryShowFatalMessage(Exception ex)
    {
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
