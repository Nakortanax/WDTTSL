using Microsoft.Win32;
using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace VPNSL.Windows;

public partial class MainWindow : Window
{
    private readonly VpnEngine _engine = new();
    private AppSettings _settings = SettingsStore.Load();
    private readonly Stopwatch _uptime = new();
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(1) };
    private string? _generatedHost;
    private List<string> _generatedAddresses = [];
    private bool _closing;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += (_, _) => LoadSettingsIntoUi();
        Closing += MainWindow_Closing;
        _timer.Tick += (_, _) => UptimeText.Text = _uptime.Elapsed.ToString(@"hh\:mm\:ss");

        _engine.Log += line => Dispatcher.Invoke(() => AppendLog(line));
        _engine.StatusChanged += status => Dispatcher.Invoke(() => SetStatus(status));
        _engine.StatsChanged += (active, up, down) => Dispatcher.Invoke(() =>
        {
            WorkersStatus.Text = active.ToString();
            UpStatus.Text = FormatBytes(up);
            DownStatus.Text = FormatBytes(down);
        });
    }

    private void LoadSettingsIntoUi()
    {
        PeerBox.Text = _settings.Peer;
        PasswordBox.Password = _settings.Password;
        VkHashesBox.Text = _settings.VkHashes;
        WorkersBox.Text = _settings.Workers.ToString();
        TurnHostBox.Text = _settings.TurnHost;
        TurnPortBox.Text = _settings.TurnPort;
        SniBox.Text = _settings.Sni;
        ClientIdsBox.Text = _settings.ClientIds;
        SetCombo(TurnTransportBox, _settings.TurnTransport);
        SetCombo(ObfsBox, _settings.Obfs);
        SetCombo(VkAuthBox, _settings.VkAuthMode);
        SetCombo(CaptchaBox, _settings.CaptchaMode);
        SetCombo(FingerprintBox, _settings.Fingerprint);
        SetCombo(RouteTargetBox, "VPNSL");
        RefreshRoutes();
        RefreshConnectionSummary();
    }

    private void SaveSettingsFromUi()
    {
        _settings.Peer = PeerBox.Text.Trim();
        _settings.Password = PasswordBox.Password;
        _settings.VkHashes = VkHashesBox.Text.Trim();
        _settings.Workers = int.TryParse(WorkersBox.Text, out var workers) ? Math.Clamp(workers, 9, 126) / 9 * 9 : 18;
        _settings.TurnHost = TurnHostBox.Text.Trim();
        _settings.TurnPort = TurnPortBox.Text.Trim();
        _settings.Sni = SniBox.Text.Trim();
        _settings.TurnTransport = ComboText(TurnTransportBox, "udp");
        _settings.Obfs = ComboText(ObfsBox, "audio");
        _settings.VkAuthMode = ComboText(VkAuthBox, "vkcalls");
        _settings.CaptchaMode = ComboText(CaptchaBox, "auto");
        _settings.Fingerprint = ComboText(FingerprintBox, "chrome");
        _settings.ClientIds = ClientIdsBox.Text.Trim();
        SettingsStore.Save(_settings);
        RefreshConnectionSummary();
    }

    private async void ConnectButton_Click(object sender, RoutedEventArgs e)
    {
        ConnectButton.IsEnabled = false;
        try
        {
            if (_engine.IsActive)
            {
                await _engine.DisconnectAsync();
                return;
            }
            SaveSettingsFromUi();
            await _engine.ConnectAsync(_settings);
        }
        catch (OperationCanceledException)
        {
            AppendLog("[WINDOWS] Подключение отменено");
        }
        catch (Exception ex)
        {
            AppendLog($"[ОШИБКА] {ex.Message}");
            MessageBox.Show(this, ex.Message, "VPNSL", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            ConnectButton.IsEnabled = true;
        }
    }

    private void SaveSettings_Click(object sender, RoutedEventArgs e)
    {
        SaveSettingsFromUi();
        AppendLog("[НАСТРОЙКИ] Сохранено");
    }

    private async void AddRoute_Click(object sender, RoutedEventArgs e)
    {
        var name = RouteNameBox.Text.Trim();
        var raw = RouteCidrBox.Text.Trim();
        if (name.Length == 0) { MessageBox.Show(this, "Введите подпись ресурса.", "VPNSL"); return; }
        if (!RoutePolicy.TryNormalize(raw, out var cidr)) { MessageBox.Show(this, "Некорректный IPv4/CIDR.", "VPNSL"); return; }

        _settings.Routes.Insert(0, new RouteProfile
        {
            Name = name,
            Enabled = true,
            Target = ComboText(RouteTargetBox, "VPNSL") == "MOBILE" ? RouteTarget.MOBILE : RouteTarget.VPNSL,
            Routes = [cidr],
        });
        SettingsStore.Save(_settings);
        RouteNameBox.Clear();
        RouteCidrBox.Clear();
        RefreshRoutes();
        AppendLog($"[ROUTE] Добавлен {name}: {cidr}");
        await RestartIfConnectedAsync();
    }

    private async void ImportRoutes_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Filter = "Маршруты (*.bat;*.txt;*.list)|*.bat;*.txt;*.list|Все файлы (*.*)|*.*",
            Multiselect = false,
        };
        if (dialog.ShowDialog(this) != true) return;
        try
        {
            var text = ReadRouteText(dialog.FileName);
            var routes = RoutePolicy.ParseRouteFile(text);
            if (routes.Count == 0) { MessageBox.Show(this, "Маршруты в файле не найдены.", "VPNSL"); return; }
            _settings.Routes.Insert(0, new RouteProfile
            {
                Name = Path.GetFileName(dialog.FileName),
                Enabled = true,
                Target = RouteTarget.VPNSL,
                Routes = routes,
            });
            SettingsStore.Save(_settings);
            RefreshRoutes();
            AppendLog($"[ROUTE] Импортировано: {routes.Count} из {Path.GetFileName(dialog.FileName)}");
            await RestartIfConnectedAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Ошибка импорта", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void ExportRoutes_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new SaveFileDialog
        {
            Filter = "BAT (*.bat)|*.bat",
            FileName = $"VPNSL-routes-{DateTime.Now:yyyyMMdd-HHmmss}.bat",
        };
        if (dialog.ShowDialog(this) != true) return;
        File.WriteAllText(dialog.FileName, RoutePolicy.BuildAllRoutesFile(_settings.Routes), new UTF8Encoding(false));
        AppendLog($"[ROUTE] Экспорт: {dialog.FileName}");
    }

    private async void RouteEnabled_Changed(object sender, RoutedEventArgs e)
    {
        if (!IsLoaded) return;
        SettingsStore.Save(_settings);
        await RestartIfConnectedAsync();
    }

    private async void ChangeRouteTarget_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string id }) return;
        var profile = _settings.Routes.FirstOrDefault(x => x.Id == id);
        if (profile is null) return;
        profile.Target = profile.Target == RouteTarget.VPNSL ? RouteTarget.MOBILE : RouteTarget.VPNSL;
        SettingsStore.Save(_settings);
        RefreshRoutes();
        await RestartIfConnectedAsync();
    }

    private async void DeleteRoute_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string id }) return;
        _settings.Routes.RemoveAll(x => x.Id == id);
        SettingsStore.Save(_settings);
        RefreshRoutes();
        await RestartIfConnectedAsync();
    }

    private async void ResolveSite_Click(object sender, RoutedEventArgs e)
    {
        SiteResultText.Text = "Поиск IPv4…";
        SaveSiteBatButton.IsEnabled = false;
        try
        {
            var result = await RoutePolicy.ResolveSiteAsync(SiteBox.Text);
            _generatedHost = result.Host;
            _generatedAddresses = result.Addresses;
            SiteResultText.Text = result.Addresses.Count == 0
                ? $"IPv4 для {result.Host} не найдены"
                : $"{result.Host}: {string.Join(", ", result.Addresses)}";
            SaveSiteBatButton.IsEnabled = result.Addresses.Count > 0;
        }
        catch (Exception ex)
        {
            SiteResultText.Text = ex.Message;
        }
    }

    private void SaveSiteBat_Click(object sender, RoutedEventArgs e)
    {
        if (_generatedHost is null || _generatedAddresses.Count == 0) return;
        var dialog = new SaveFileDialog
        {
            Filter = "BAT (*.bat)|*.bat",
            FileName = $"{SanitizeFileName(_generatedHost)}.bat",
        };
        if (dialog.ShowDialog(this) != true) return;
        File.WriteAllText(dialog.FileName, RoutePolicy.BuildSiteRoutesFile(_generatedHost, _generatedAddresses), new UTF8Encoding(false));
    }

    private void Nav_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button button) return;
        ShowPage(button.Tag?.ToString() ?? "connection");
    }

    private void ShowPage(string page)
    {
        ConnectionPage.Visibility = page == "connection" ? Visibility.Visible : Visibility.Collapsed;
        SettingsPage.Visibility = page == "settings" ? Visibility.Visible : Visibility.Collapsed;
        RoutingPage.Visibility = page == "routing" ? Visibility.Visible : Visibility.Collapsed;
        ServerPage.Visibility = page == "server" ? Visibility.Visible : Visibility.Collapsed;
        LogsPage.Visibility = page == "logs" ? Visibility.Visible : Visibility.Collapsed;
        InfoPage.Visibility = page == "info" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void SetStatus(string status)
    {
        HeaderStatus.Text = status;
        ConnectionStatus.Text = status;
        if (status == "Подключено")
        {
            ConnectButton.Content = "Отключить";
            if (!_uptime.IsRunning)
            {
                _uptime.Start();
                _timer.Start();
            }
        }
        else if (status == "Отключено")
        {
            ConnectButton.Content = "Подключить";
            _timer.Stop();
            _uptime.Reset();
            UptimeText.Text = "00:00:00";
            WorkersStatus.Text = _settings.Workers.ToString();
        }
        else if (status.StartsWith("Отключение", StringComparison.Ordinal))
        {
            ConnectButton.Content = "Отключение…";
        }
        else
        {
            ConnectButton.Content = "Отменить подключение";
        }
    }

    private void RefreshRoutes()
    {
        RoutesList.ItemsSource = null;
        RoutesList.ItemsSource = _settings.Routes;
    }

    private void RefreshConnectionSummary()
    {
        ObfsStatus.Text = _settings.Obfs;
        WorkersStatus.Text = _settings.Workers.ToString();
        HashesStatus.Text = _settings.VkHashes
            .Split([',', ';', '\n', '\r', ' '], StringSplitOptions.RemoveEmptyEntries)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Count().ToString();
    }

    private async Task RestartIfConnectedAsync()
    {
        if (!_engine.IsRunning) return;
        try
        {
            AppendLog("[ROUTE] Применение изменённых маршрутов…");
            await _engine.DisconnectAsync();
            await _engine.ConnectAsync(_settings);
        }
        catch (Exception ex)
        {
            AppendLog($"[ROUTE] Ошибка переподключения: {ex.Message}");
        }
    }

    private void AppendLog(string line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        LogBox.AppendText($"{DateTime.Now:HH:mm:ss} {line}{Environment.NewLine}");
        if (LogBox.Text.Length > 500_000) LogBox.Text = LogBox.Text[^350_000..];
        LogBox.ScrollToEnd();
    }

    private void ClearLogs_Click(object sender, RoutedEventArgs e) => LogBox.Clear();

    private void OpenRepo_Click(object sender, RoutedEventArgs e)
    {
        Process.Start(new ProcessStartInfo("https://github.com/Nakortanax/WDTTSL") { UseShellExecute = true });
    }

    private async void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (_closing) return;
        e.Cancel = true;
        _closing = true;
        try
        {
            SaveSettingsFromUi();
            await _engine.DisconnectAsync();
        }
        catch { }
        Close();
    }

    private static string ComboText(ComboBox combo, string fallback) =>
        (combo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? combo.Text.NullIfWhiteSpace() ?? fallback;

    private static void SetCombo(ComboBox combo, string value)
    {
        foreach (var item in combo.Items.OfType<ComboBoxItem>())
            if (string.Equals(item.Content?.ToString(), value, StringComparison.OrdinalIgnoreCase)) { combo.SelectedItem = item; return; }
        combo.SelectedIndex = combo.Items.Count > 0 ? 0 : -1;
    }

    private static string ReadRouteText(string path)
    {
        var bytes = File.ReadAllBytes(path);
        if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF) return Encoding.UTF8.GetString(bytes, 3, bytes.Length - 3);
        try { return new UTF8Encoding(false, true).GetString(bytes); }
        catch { return Encoding.Default.GetString(bytes); }
    }

    private static string SanitizeFileName(string value) => string.Concat(value.Select(ch => Path.GetInvalidFileNameChars().Contains(ch) ? '_' : ch));
    private static string FormatBytes(long bytes) => bytes switch
    {
        < 1024 => $"{bytes} B",
        < 1024 * 1024 => $"{bytes / 1024d:F1} KB",
        < 1024L * 1024 * 1024 => $"{bytes / (1024d * 1024):F1} MB",
        _ => $"{bytes / (1024d * 1024 * 1024):F2} GB",
    };
}

internal static class UiStringExtensions
{
    public static string? NullIfWhiteSpace(this string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}