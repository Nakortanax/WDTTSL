using System.Text.Json;
using System.Text.Json.Serialization;

namespace VPNSL.Windows;

public enum RouteTarget
{
    MOBILE,
    VPNSL,
}

public sealed class RouteProfile
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Name { get; set; } = "Маршрут";
    public bool Enabled { get; set; } = true;
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public RouteTarget Target { get; set; } = RouteTarget.VPNSL;
    public List<string> Routes { get; set; } = [];

    [JsonIgnore]
    public string TargetDisplay => Target == RouteTarget.VPNSL ? "Через VPNSL" : "Напрямую";

    [JsonIgnore]
    public string RouteCountDisplay => Routes.Count switch
    {
        1 => "1 маршрут",
        >= 2 and <= 4 => $"{Routes.Count} маршрута",
        _ => $"{Routes.Count} маршрутов",
    };

    [JsonIgnore]
    public string EnabledDisplay => Enabled ? "Включено" : "Выключено";
}

public sealed class AppSettings
{
    public string Peer { get; set; } = "";
    public string Password { get; set; } = "";
    public string VkHashes { get; set; } = "";
    public string VkHashMode { get; set; } = "manual";
    public int Workers { get; set; } = 18;
    public string TurnHost { get; set; } = "";
    public string TurnPort { get; set; } = "";
    public string Sni { get; set; } = "";
    public string Obfs { get; set; } = "audio";
    public string TurnTransport { get; set; } = "udp";
    public string VkAuthMode { get; set; } = "vkcalls";
    public string CaptchaMode { get; set; } = "auto";
    public string Fingerprint { get; set; } = "chrome";
    public string ClientIds { get; set; } = "8202606,6287487";
    public string DeviceId { get; set; } = Guid.NewGuid().ToString("N");

    public string SshHost { get; set; } = "";
    public string SshUser { get; set; } = "root";
    public string SshPassword { get; set; } = "";
    public int SshPort { get; set; } = 22;
    public int ServerPeerPort { get; set; } = 46000;
    public int ServerWebPort { get; set; } = 46002;
    public string ServerMainPassword { get; set; } = "";
    public string ServerWebLogin { get; set; } = "";
    public string ServerWebPassword { get; set; } = "";
    public bool ServerDockerInstall { get; set; }
    public string SshPrivateKeyPath { get; set; } = "";
    public string SshPrivateKeyPassphrase { get; set; } = "";

    public List<RouteProfile> Routes { get; set; } = [];
}

public static class SettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    public static string DirectoryPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "VPNSL");

    public static string FilePath => Path.Combine(DirectoryPath, "settings.json");

    public static AppSettings Load()
    {
        try
        {
            if (!File.Exists(FilePath)) return new AppSettings();
            var loaded = JsonSerializer.Deserialize<AppSettings>(File.ReadAllText(FilePath), JsonOptions);
            if (loaded is null) return new AppSettings();
            if (string.IsNullOrWhiteSpace(loaded.DeviceId)) loaded.DeviceId = Guid.NewGuid().ToString("N");
            loaded.Routes ??= [];
            return loaded;
        }
        catch
        {
            return new AppSettings();
        }
    }

    public static void Save(AppSettings settings)
    {
        Directory.CreateDirectory(DirectoryPath);
        var temp = FilePath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(settings, JsonOptions));
        File.Move(temp, FilePath, true);
    }
}