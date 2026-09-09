using Microsoft.Win32;
using System.ComponentModel;
using System.Diagnostics;
using System.Windows;

namespace VPNSL.Windows;

public partial class MainWindow
{
    private bool _serverUiLoaded;
    private bool _serverBusy;

    protected override void OnInitialized(EventArgs e)
    {
        base.OnInitialized(e);
        Loaded += ServerWindow_Loaded;
        Closing += ServerWindow_Closing;
    }

    private void ServerWindow_Loaded(object sender, RoutedEventArgs e)
    {
        LoadServerSettingsIntoUi();
    }

    private void ServerWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (!_serverUiLoaded || _serverBusy) return;
        SaveServerSettingsFromUi(validatePorts: false);
    }

    private void LoadServerSettingsIntoUi()
    {
        SshHostBox.Text = _settings.SshHost;
        SshPortBox.Text = _settings.SshPort.ToString();
        SshUserBox.Text = string.IsNullOrWhiteSpace(_settings.SshUser) ? "root" : _settings.SshUser;
        SshPasswordBox.Password = _settings.SshPassword;
        SshKeyPathBox.Text = _settings.SshPrivateKeyPath;
        SshKeyPassphraseBox.Password = _settings.SshPrivateKeyPassphrase;
        ServerPeerPortBox.Text = _settings.ServerPeerPort.ToString();
        ServerWebPortBox.Text = _settings.ServerWebPort.ToString();
        ServerMainPasswordBox.Password = _settings.ServerMainPassword;
        ServerWebLoginBox.Text = _settings.ServerWebLogin;
        ServerWebPasswordBox.Password = _settings.ServerWebPassword;
        ServerDockerBox.IsChecked = _settings.ServerDockerInstall;
        _serverUiLoaded = true;
    }

    private bool SaveServerSettingsFromUi(bool validatePorts = true)
    {
        if (!_serverUiLoaded) return true;

        _settings.SshHost = SshHostBox.Text.Trim();
        _settings.SshUser = string.IsNullOrWhiteSpace(SshUserBox.Text) ? "root" : SshUserBox.Text.Trim();
        _settings.SshPassword = SshPasswordBox.Password.Replace("\r", "").Replace("\n", "");
        _settings.SshPrivateKeyPath = SshKeyPathBox.Text.Trim();
        _settings.SshPrivateKeyPassphrase = SshKeyPassphraseBox.Password;
        _settings.ServerMainPassword = ServerMainPasswordBox.Password;
        _settings.ServerWebLogin = ServerWebLoginBox.Text.Trim();
        _settings.ServerWebPassword = ServerWebPasswordBox.Password;
        _settings.ServerDockerInstall = ServerDockerBox.IsChecked == true;

        if (TryReadPort(SshPortBox.Text, out var sshPort)) _settings.SshPort = sshPort;
        else if (validatePorts) return ShowBadPort("SSH port");

        if (TryReadPort(ServerPeerPortBox.Text, out var peerPort)) _settings.ServerPeerPort = peerPort;
        else if (validatePorts) return ShowBadPort("Peer port");

        if (TryReadPort(ServerWebPortBox.Text, out var webPort)) _settings.ServerWebPort = webPort;
        else if (validatePorts) return ShowBadPort("Web port");

        SettingsStore.Save(_settings);
        return true;
    }

    private static bool TryReadPort(string raw, out int port) =>
        int.TryParse(raw.Trim(), out port) && port is >= 1 and <= 65535;

    private bool ShowBadPort(string name)
    {
        MessageBox.Show(this, $"Некорректный {name}. Допустимый диапазон: 1–65535.", "VPNSL", MessageBoxButton.OK, MessageBoxImage.Warning);
        return false;
    }

    private ServerDeployService CreateServerDeployService() => new(
        line => Dispatcher.Invoke(() => AppendLog(line)),
        status => Dispatcher.Invoke(() => ServerDeployStatusText.Text = status));

    private void BrowseSshKey_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "Выберите приватный SSH-ключ",
            Filter = "Приватные ключи|id_*;*.pem;*.key;*.ppk|Все файлы (*.*)|*.*",
            CheckFileExists = true,
        };
        if (dialog.ShowDialog(this) != true) return;
        SshKeyPathBox.Text = dialog.FileName;
        SaveServerSettingsFromUi(validatePorts: false);
    }

    private async void TestSsh_Click(object sender, RoutedEventArgs e)
    {
        if (!SaveServerSettingsFromUi()) return;
        await RunServerActionAsync("Проверка SSH…", async service =>
        {
            var result = await service.TestConnectionAsync(_settings);
            var parts = result.Split('|');
            var description = parts.Length >= 3
                ? $"Архитектура: {parts[0]}\nИмя сервера: {parts[1]}\nUID: {parts[2]}"
                : result;
            AppendLog($"[SSH] Проверка успешна: {result}");
            MessageBox.Show(this, description, "SSH подключение успешно", MessageBoxButton.OK, MessageBoxImage.Information);
        });
    }

    private async void InstallServer_Click(object sender, RoutedEventArgs e)
    {
        if (!SaveServerSettingsFromUi()) return;
        var answer = MessageBox.Show(
            this,
            "Установить или переустановить VPNSL 1.0.8 на указанном VPS?\n\nРаботающий сервер будет заменён штатным deploy.sh версии 1.0.8.",
            "Установка VPNSL",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);
        if (answer != MessageBoxResult.Yes) return;

        await RunServerActionAsync("Установка VPNSL…", async service =>
        {
            await service.InstallAsync(_settings);
            PasswordBox.Password = _settings.Password;
            SaveSettingsFromUi();
            MessageBox.Show(this, "VPNSL 1.0.8 успешно установлен на VPS.", "VPNSL", MessageBoxButton.OK, MessageBoxImage.Information);
        });
    }

    private async void UninstallServer_Click(object sender, RoutedEventArgs e)
    {
        if (!SaveServerSettingsFromUi()) return;
        var answer = MessageBox.Show(
            this,
            "Удалить VPNSL с указанного VPS?\n\nЭто остановит и удалит серверную часть VPNSL.",
            "Удаление VPNSL",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning);
        if (answer != MessageBoxResult.Yes) return;

        await RunServerActionAsync("Удаление VPNSL…", async service =>
        {
            await service.UninstallAsync(_settings);
            MessageBox.Show(this, "VPNSL удалён с VPS.", "VPNSL", MessageBoxButton.OK, MessageBoxImage.Information);
        });
    }

    private void OpenServerPanel_Click(object sender, RoutedEventArgs e)
    {
        if (!SaveServerSettingsFromUi()) return;
        var host = _settings.SshHost.Trim();
        if (host.Length == 0)
        {
            MessageBox.Show(this, "Укажите адрес VPS.", "VPNSL", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (host.StartsWith("http://", StringComparison.OrdinalIgnoreCase)) host = host[7..];
        else if (host.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) host = host[8..];
        host = host.TrimEnd('/');
        var url = $"http://{host}:{_settings.ServerWebPort}/";
        try
        {
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Не удалось открыть web-панель", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private async Task RunServerActionAsync(string initialStatus, Func<ServerDeployService, Task> action)
    {
        if (_serverBusy) return;
        _serverBusy = true;
        ServerPage.IsEnabled = false;
        ServerProgress.Visibility = Visibility.Visible;
        ServerDeployStatusText.Text = initialStatus;
        try
        {
            await action(CreateServerDeployService());
            ServerDeployStatusText.Text = "Готово";
        }
        catch (OperationCanceledException)
        {
            ServerDeployStatusText.Text = "Отменено";
            AppendLog("[SERVER] Операция отменена");
        }
        catch (Exception ex)
        {
            ServerDeployStatusText.Text = "Ошибка";
            AppendLog($"[SERVER-ERR] {ex.Message}");
            MessageBox.Show(this, ex.Message, "Ошибка сервера VPNSL", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            ServerProgress.Visibility = Visibility.Collapsed;
            ServerPage.IsEnabled = true;
            _serverBusy = false;
            SaveServerSettingsFromUi(validatePorts: false);
        }
    }
}
