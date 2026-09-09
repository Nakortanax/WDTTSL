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
            if (!IsAdministrator())
            {
                if (!TryRelaunchElevated())
                    MessageBox.Show("Для работы VPNSL требуются права администратора.", "VPNSL", MessageBoxButton.OK, MessageBoxImage.Warning);

                Shutdown();
                return;
            }

            var window = new MainWindow();
            MainWindow = window;
            window.Show();
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

            Process.Start(new ProcessStartInfo(executable)
            {
                UseShellExecute = true,
                Verb = "runas",
                WorkingDirectory = AppContext.BaseDirectory,
            });
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

    private void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        ShowStartupError(e.Exception);
        e.Handled = true;
        Shutdown(-1);
    }

    private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
            WriteStartupLog(ex);
    }

    private static void ShowStartupError(Exception ex)
    {
        WriteStartupLog(ex);
        MessageBox.Show(
            $"VPNSL не удалось запустить.\n\n{ex.Message}\n\nПодробности записаны в startup-error.log.",
            "VPNSL — ошибка запуска",
            MessageBoxButton.OK,
            MessageBoxImage.Error);
    }

    private static void WriteStartupLog(Exception ex)
    {
        try
        {
            Directory.CreateDirectory(SettingsStore.DirectoryPath);
            var path = Path.Combine(SettingsStore.DirectoryPath, "startup-error.log");
            File.AppendAllText(path, $"[{DateTimeOffset.Now:O}]\r\n{ex}\r\n\r\n");
        }
        catch
        {
        }
    }
}
