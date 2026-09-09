using System.ComponentModel;
using System.Diagnostics;
using System.Security.Principal;
using System.Windows;
using System.Windows.Threading;

namespace VPNSL.Windows;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;

        try
        {
            WriteStartupTrace($"START pid={Environment.ProcessId}; exe={Environment.ProcessPath}; base={AppContext.BaseDirectory}");

            if (!IsAdministrator())
            {
                WriteStartupTrace("Process is not elevated; requesting UAC elevation.");
                if (!TryRelaunchElevated())
                {
                    WriteStartupTrace("Elevation was cancelled or could not be started.");
                    MessageBox.Show(
                        "Для работы VPNSL требуются права администратора. Запуск отменён.",
                        "VPNSL",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning);
                }

                Shutdown();
                return;
            }

            WriteStartupTrace("Process is elevated.");
            ValidateRuntimePackage();

            var window = new MainWindow();
            MainWindow = window;
            window.Show();
            WriteStartupTrace("Main window shown successfully.");
        }
        catch (Exception ex)
        {
            ShowStartupError(ex);
            Shutdown(-1);
        }
    }

    private static bool IsAdministrator()
    {
        using var identity = WindowsIdentity.GetCurrent();
        var principal = new WindowsPrincipal(identity);
        return principal.IsInRole(WindowsBuiltInRole.Administrator);
    }

    private static bool TryRelaunchElevated()
    {
        try
        {
            var executable = Environment.ProcessPath;
            if (string.IsNullOrWhiteSpace(executable))
                throw new InvalidOperationException("Не удалось определить путь к VPNSL.Windows.exe");

            var process = Process.Start(new ProcessStartInfo(executable)
            {
                UseShellExecute = true,
                Verb = "runas",
                WorkingDirectory = AppContext.BaseDirectory,
            });

            if (process is null)
                throw new InvalidOperationException("Windows не запустил повышенный процесс VPNSL.");

            WriteStartupTrace($"Elevated process requested, pid={process.Id}.");
            return true;
        }
        catch (Win32Exception ex) when (ex.NativeErrorCode == 1223)
        {
            return false;
        }
        catch (Exception ex)
        {
            ShowStartupError(ex);
            return false;
        }
    }

    private static void ValidateRuntimePackage()
    {
        var missing = new List<string>();
        foreach (var fileName in new[] { "client.exe", "wintun.dll" })
        {
            var path = Path.Combine(AppContext.BaseDirectory, fileName);
            if (!File.Exists(path)) missing.Add(fileName);
        }

        if (missing.Count == 0)
        {
            WriteStartupTrace("Runtime package preflight passed.");
            return;
        }

        throw new FileNotFoundException(
            "Пакет VPNSL распакован или установлен не полностью. Отсутствуют файлы: " +
            string.Join(", ", missing) +
            ". Не запускайте VPNSL.Windows.exe отдельно от остальных файлов portable-папки.");
    }

    private void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        ShowStartupError(e.Exception);
        e.Handled = true;
        Shutdown(-1);
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
            WriteStartupError(ex);
    }

    private static void ShowStartupError(Exception ex)
    {
        WriteStartupError(ex);
        MessageBox.Show(
            $"VPNSL не удалось запустить.\n\n{ex.Message}\n\nДиагностика: %APPDATA%\\VPNSL\\startup.log",
            "VPNSL — ошибка запуска",
            MessageBoxButton.OK,
            MessageBoxImage.Error);
    }

    private static void WriteStartupError(Exception ex)
    {
        WriteStartupTrace("ERROR\r\n" + ex);
    }

    private static void WriteStartupTrace(string message)
    {
        try
        {
            Directory.CreateDirectory(SettingsStore.DirectoryPath);
            var path = Path.Combine(SettingsStore.DirectoryPath, "startup.log");
            File.AppendAllText(path, $"[{DateTimeOffset.Now:O}] {message}\r\n");
        }
        catch
        {
        }
    }
}
