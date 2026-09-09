using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;

namespace VPNSL.Windows;

public static partial class RoutePolicy
{
    [GeneratedRegex(@"^\s*route\s+(?:-p\s+)?add\s+(?<ip>\d{1,3}(?:\.\d{1,3}){3})\s+mask\s+(?<mask>\d{1,3}(?:\.\d{1,3}){3})(?:\s+\S+)?", RegexOptions.IgnoreCase)]
    private static partial Regex RouteAddRegex();

    public static bool TryNormalize(string raw, out string cidr)
    {
        cidr = "";
        raw = raw.Trim();
        if (raw.Length == 0) return false;
        var parts = raw.Split('/', 2, StringSplitOptions.TrimEntries);
        if (!IPAddress.TryParse(parts[0], out var address) || address.AddressFamily != AddressFamily.InterNetwork)
            return false;
        var prefix = 32;
        if (parts.Length == 2 && (!int.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out prefix) || prefix is < 0 or > 32))
            return false;

        var value = ToUInt32(address);
        var mask = PrefixMask(prefix);
        var network = value & mask;
        cidr = $"{FromUInt32(network)}/{prefix}";
        return true;
    }

    public static List<string> ParseRouteFile(string text)
    {
        var routes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var original in text.Replace("\r", "").Split('\n'))
        {
            var line = original.Trim();
            if (line.Length == 0 || line.StartsWith("REM ", StringComparison.OrdinalIgnoreCase) || line.StartsWith("#") || line.StartsWith("::"))
                continue;

            var match = RouteAddRegex().Match(line);
            if (match.Success && TryMaskToPrefix(match.Groups["mask"].Value, out var prefix) &&
                TryNormalize($"{match.Groups["ip"].Value}/{prefix}", out var fromBat))
            {
                routes.Add(fromBat);
                continue;
            }

            var token = line.Split([' ', '\t', ','], StringSplitOptions.RemoveEmptyEntries).FirstOrDefault();
            if (token is not null && TryNormalize(token, out var direct)) routes.Add(direct);
        }
        return routes.Order(StringComparer.OrdinalIgnoreCase).ToList();
    }

    public static string BuildAllRoutesFile(IEnumerable<RouteProfile> profiles)
    {
        var sb = new StringBuilder();
        sb.AppendLine("REM VPNSL routes export");
        sb.AppendLine("REM All saved route profiles are included, including disabled ones.");
        sb.AppendLine("REM Network selection and active state are informational comments in BAT format.");
        var first = true;
        foreach (var profile in profiles)
        {
            if (!first) sb.AppendLine();
            first = false;
            sb.AppendLine($"REM {SafeComment(profile.Name)} | {(profile.Enabled ? "enabled" : "disabled")} | {profile.Target}");
            foreach (var route in profile.Routes) sb.AppendLine(ToBatCommand(route));
        }
        return sb.ToString();
    }

    public static string BuildSiteRoutesFile(string host, IEnumerable<string> ipv4)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"REM VPNSL route file for {SafeComment(host)}");
        foreach (var address in ipv4.Distinct().Order(StringComparer.OrdinalIgnoreCase))
            sb.AppendLine(ToBatCommand(address.Contains('/') ? address : address + "/32"));
        return sb.ToString();
    }

    public static async Task<(string Host, List<string> Addresses)> ResolveSiteAsync(string input, CancellationToken cancellationToken = default)
    {
        var text = input.Trim();
        if (text.Length == 0) throw new ArgumentException("Введите имя сайта");
        if (!text.Contains("://", StringComparison.Ordinal)) text = "https://" + text;
        if (!Uri.TryCreate(text, UriKind.Absolute, out var uri) || string.IsNullOrWhiteSpace(uri.Host))
            throw new ArgumentException("Некорректное имя сайта");

        var host = new IdnMapping().GetAscii(uri.Host.TrimEnd('.')).ToLowerInvariant();
        var addresses = await Dns.GetHostAddressesAsync(host, cancellationToken);
        var result = addresses
            .Where(a => a.AddressFamily == AddressFamily.InterNetwork)
            .Select(a => a.ToString())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Order(StringComparer.OrdinalIgnoreCase)
            .ToList();
        return (host, result);
    }

    public static string ToBatCommand(string cidr)
    {
        if (!TryNormalize(cidr, out var normalized)) throw new ArgumentException($"Некорректный IPv4/CIDR: {cidr}");
        var slash = normalized.LastIndexOf('/');
        var ip = normalized[..slash];
        var prefix = int.Parse(normalized[(slash + 1)..], CultureInfo.InvariantCulture);
        return $"route add {ip} mask {PrefixToMask(prefix)} 0.0.0.0";
    }

    public static string PrefixToMask(int prefix)
    {
        if (prefix is < 0 or > 32) throw new ArgumentOutOfRangeException(nameof(prefix));
        return FromUInt32(PrefixMask(prefix)).ToString();
    }

    private static bool TryMaskToPrefix(string raw, out int prefix)
    {
        prefix = 0;
        if (!IPAddress.TryParse(raw, out var address) || address.AddressFamily != AddressFamily.InterNetwork) return false;
        var mask = ToUInt32(address);
        var seenZero = false;
        for (var bit = 31; bit >= 0; bit--)
        {
            var one = (mask & (1u << bit)) != 0;
            if (!one) seenZero = true;
            else if (seenZero) return false;
            else prefix++;
        }
        return true;
    }

    private static uint PrefixMask(int prefix) => prefix == 0 ? 0u : uint.MaxValue << (32 - prefix);

    private static uint ToUInt32(IPAddress address)
    {
        var b = address.GetAddressBytes();
        return ((uint)b[0] << 24) | ((uint)b[1] << 16) | ((uint)b[2] << 8) | b[3];
    }

    private static IPAddress FromUInt32(uint value) => new([
        (byte)(value >> 24), (byte)(value >> 16), (byte)(value >> 8), (byte)value]);

    private static string SafeComment(string value) => value.Replace('\r', ' ').Replace('\n', ' ').Trim();
}
