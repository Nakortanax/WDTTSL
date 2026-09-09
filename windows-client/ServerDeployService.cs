using Renci.SshNet;
using Renci.SshNet.Common;
using System.Text;
using System.Text.Json;

namespace VPNSL.Windows;

internal sealed class ServerDeployService
{
    private readonly Action<string> _log;
    private readonly Action<string>? _status;

    public ServerDeployService(Action<string> log, Action<string>? status = null)
    {
        _log = log;
        _status = status;
    }

    public async Task InstallAsync(AppSettings settings, CancellationToken cancellationToken = default)
    {
        Validate(settings, requireServerPasswords: true);
        var assets = GetAssetsDirectory();
        var deployScript = RequireFile(Path.Combine(assets, "deploy.sh"));

        _status?.Invoke("Подключение по SSH…");
        using var ssh = CreateSshClient(settings);
        await Task.Run(ssh.Connect, cancellationToken);
        _log($"[SSH] Подключено к {settings.SshHost}:{settings.SshPort} как {settings.SshUser}");

        var archResult = await RunCommandAsync(ssh, "uname -m", cancellationToken);
        EnsureSuccess(archResult, "Не удалось определить архитектуру VPS");
        var architecture = archResult.Output.Trim().Split('\n', StringSplitOptions.RemoveEmptyEntries).FirstOrDefault()?.Trim() ?? "";
        var binaryName = MapServerBinary(architecture);
        var serverBinary = RequireFile(Path.Combine(assets, binaryName));
        _log($"[SSH] Архитектура VPS: {architecture} -> {binaryName}");

        _status?.Invoke("Загрузка файлов…");
        using (var sftp = CreateSftpClient(settings))
        {
            await Task.Run(sftp.Connect, cancellationToken);
            await UploadFileAsync(sftp, deployScript, "/tmp/deploy.sh", cancellationToken);
            await UploadFileAsync(sftp, serverBinary, "/tmp/.csqtt-upload-server", cancellationToken);

            var webEnv = BuildWebEnv(settings);
            await UploadBytesAsync(sftp, Encoding.UTF8.GetBytes(webEnv), "/tmp/.csqtt-upload-web.env", cancellationToken);

            var overrides = JsonSerializer.Serialize(new
            {
                main_password = settings.ServerMainPassword,
                device_id = settings.DeviceId,
            });
            await UploadBytesAsync(sftp, Encoding.UTF8.GetBytes(overrides), "/tmp/.csqtt-upload-overrides.json", cancellationToken);
            sftp.Disconnect();
        }

        _status?.Invoke("Установка VPNSL…");
        var mode = settings.ServerDockerInstall ? "docker" : "systemd";
        var environment = $"env CSQTT_PEER_PORT={settings.ServerPeerPort} CSQTT_SSH_PORT={settings.SshPort} CSQTT_WEB_PORT={settings.ServerWebPort} CSQTT_DEPLOY_MODE={mode}";
        var install = await RunRootCommandAsync(ssh, settings, $"{environment} bash /tmp/deploy.sh install", cancellationToken);
        if (!string.IsNullOrWhiteSpace(install.Output)) _log(TrimForLog("[SERVER] ", install.Output));
        if (!string.IsNullOrWhiteSpace(install.Error)) _log(TrimForLog("[SERVER-ERR] ", install.Error));
        EnsureSuccess(install, "Установка сервера завершилась с ошибкой");
        if (!install.Output.Replace("\r", "").Split('\n').Any(line => line.Trim() == "CSQTT_DEPLOY_OK"))
            throw new InvalidOperationException("Скрипт установки не вернул контрольную строку CSQTT_DEPLOY_OK.");

        settings.Password = settings.ServerMainPassword;
        SettingsStore.Save(settings);
        _status?.Invoke("Сервер установлен");
        _log("[SERVER] VPNSL 1.0.8 установлен успешно");
    }

    public async Task UninstallAsync(AppSettings settings, CancellationToken cancellationToken = default)
    {
        Validate(settings, requireServerPasswords: false);
        var deployScript = RequireFile(Path.Combine(GetAssetsDirectory(), "deploy.sh"));

        _status?.Invoke("Подключение по SSH…");
        using var ssh = CreateSshClient(settings);
        await Task.Run(ssh.Connect, cancellationToken);

        using (var sftp = CreateSftpClient(settings))
        {
            await Task.Run(sftp.Connect, cancellationToken);
            await UploadFileAsync(sftp, deployScript, "/tmp/deploy.sh", cancellationToken);
            sftp.Disconnect();
        }

        _status?.Invoke("Удаление VPNSL…");
        var environment = $"env CSQTT_PEER_PORT={settings.ServerPeerPort} CSQTT_SSH_PORT={settings.SshPort}";
        var result = await RunRootCommandAsync(ssh, settings, $"{environment} bash /tmp/deploy.sh uninstall", cancellationToken);
        if (!string.IsNullOrWhiteSpace(result.Output)) _log(TrimForLog("[SERVER] ", result.Output));
        if (!string.IsNullOrWhiteSpace(result.Error)) _log(TrimForLog("[SERVER-ERR] ", result.Error));
        EnsureSuccess(result, "Удаление сервера завершилось с ошибкой");
        _status?.Invoke("Сервер удалён");
        _log("[SERVER] VPNSL удалён с VPS");
    }

    public async Task<string> TestConnectionAsync(AppSettings settings, CancellationToken cancellationToken = default)
    {
        Validate(settings, requireServerPasswords: false);
        using var ssh = CreateSshClient(settings);
        await Task.Run(ssh.Connect, cancellationToken);
        var result = await RunCommandAsync(ssh, "printf '%s|%s|%s' \"$(uname -m)\" \"$(hostname 2>/dev/null || echo unknown)\" \"$(id -u)\"", cancellationToken);
        EnsureSuccess(result, "SSH-проверка завершилась с ошибкой");
        return result.Output.Trim();
    }

    private SshClient CreateSshClient(AppSettings settings)
    {
        var client = new SshClient(BuildConnectionInfo(settings));
        client.HostKeyReceived += (_, e) => e.CanTrust = true; // Matches Android 1.0.8 behavior.
        return client;
    }

    private SftpClient CreateSftpClient(AppSettings settings)
    {
        var client = new SftpClient(BuildConnectionInfo(settings));
        client.HostKeyReceived += (_, e) => e.CanTrust = true; // Matches Android 1.0.8 behavior.
        return client;
    }

    private static ConnectionInfo BuildConnectionInfo(AppSettings settings)
    {
        var methods = new List<AuthenticationMethod>();
        if (!string.IsNullOrWhiteSpace(settings.SshPrivateKeyPath))
        {
            var key = new PrivateKeyFile(
                settings.SshPrivateKeyPath,
                string.IsNullOrEmpty(settings.SshPrivateKeyPassphrase) ? null : settings.SshPrivateKeyPassphrase);
            methods.Add(new PrivateKeyAuthenticationMethod(settings.SshUser, key));
        }

        if (!string.IsNullOrEmpty(settings.SshPassword))
        {
            methods.Add(new PasswordAuthenticationMethod(settings.SshUser, settings.SshPassword));
            var keyboard = new KeyboardInteractiveAuthenticationMethod(settings.SshUser);
            keyboard.AuthenticationPrompt += (_, e) =>
            {
                foreach (AuthenticationPrompt prompt in e.Prompts)
                {
                    if (prompt.Request.Contains("password", StringComparison.OrdinalIgnoreCase) || e.Prompts.Count == 1)
                        prompt.Response = settings.SshPassword;
                }
            };
            methods.Add(keyboard);
        }

        if (methods.Count == 0)
            throw new ArgumentException("Укажите SSH-пароль или приватный ключ.");

        return new ConnectionInfo(settings.SshHost, settings.SshPort, settings.SshUser, methods.ToArray())
        {
            Timeout = TimeSpan.FromSeconds(30),
        };
    }

    private static async Task<CommandResult> RunCommandAsync(SshClient ssh, string commandText, CancellationToken cancellationToken)
    {
        using var command = ssh.CreateCommand(commandText);
        command.CommandTimeout = TimeSpan.FromMinutes(5);
        await command.ExecuteAsync(cancellationToken);
        return new CommandResult(command.ExitStatus ?? -1, command.Result ?? "", command.Error ?? "");
    }

    private static async Task<CommandResult> RunRootCommandAsync(SshClient ssh, AppSettings settings, string commandText, CancellationToken cancellationToken)
    {
        var id = await RunCommandAsync(ssh, "id -u", cancellationToken);
        EnsureSuccess(id, "Не удалось проверить права пользователя SSH");
        if (id.Output.Trim() == "0")
            return await RunCommandAsync(ssh, commandText, cancellationToken);

        if (string.IsNullOrEmpty(settings.SshPassword))
            throw new InvalidOperationException("Пользователь SSH не root. Для sudo требуется SSH-пароль.");

        using var command = ssh.CreateCommand($"sudo -S -p '' bash -c {ShellQuote(commandText)}");
        command.CommandTimeout = TimeSpan.FromMinutes(10);
        var execute = command.ExecuteAsync(cancellationToken);
        using (var input = command.CreateInputStream())
        {
            var password = Encoding.UTF8.GetBytes(settings.SshPassword + "\n");
            await input.WriteAsync(password, cancellationToken);
            await input.FlushAsync(cancellationToken);
        }
        await execute;
        return new CommandResult(command.ExitStatus ?? -1, command.Result ?? "", command.Error ?? "");
    }

    private static async Task UploadFileAsync(SftpClient sftp, string localPath, string remotePath, CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(localPath);
        await Task.Run(() => sftp.UploadFile(stream, remotePath, true), cancellationToken);
    }

    private static async Task UploadBytesAsync(SftpClient sftp, byte[] bytes, string remotePath, CancellationToken cancellationToken)
    {
        using var stream = new MemoryStream(bytes, writable: false);
        await Task.Run(() => sftp.UploadFile(stream, remotePath, true), cancellationToken);
    }

    private static string BuildWebEnv(AppSettings settings)
    {
        return $"CSQTT_WEB_USER={DeployEnvironmentValue(settings.ServerWebLogin, settings.ServerDockerInstall)}\n" +
               $"CSQTT_WEB_PASS={DeployEnvironmentValue(settings.ServerWebPassword, settings.ServerDockerInstall)}\n";
    }

    private static string DeployEnvironmentValue(string value, bool docker) =>
        docker ? DockerEnvironmentValue(value) : SystemdEnvironmentValue(value);

    private static string DockerEnvironmentValue(string value) =>
        value.Replace('\n', ' ').Replace('\r', ' ');

    private static string SystemdEnvironmentValue(string value)
    {
        var builder = new StringBuilder(value.Length + 8);
        builder.Append('"');
        foreach (var ch in value)
        {
            switch (ch)
            {
                case '\\': builder.Append("\\\\"); break;
                case '"': builder.Append("\\\""); break;
                case '\n':
                case '\r': builder.Append(' '); break;
                default: builder.Append(ch); break;
            }
        }
        builder.Append('"');
        return builder.ToString();
    }

    private static string ShellQuote(string value) => "'" + value.Replace("'", "'\"'\"'") + "'";

    private static string MapServerBinary(string architecture) => architecture.Trim().ToLowerInvariant() switch
    {
        "x86_64" or "amd64" => "csqtt-linux-amd64",
        "aarch64" or "arm64" => "csqtt-linux-arm64",
        "armv7l" or "armv7" or "armhf" => "csqtt-linux-armv7",
        _ => throw new NotSupportedException($"Архитектура VPS не поддерживается: {architecture}"),
    };

    private static string GetAssetsDirectory()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "server-assets");
        if (!Directory.Exists(path))
            throw new DirectoryNotFoundException("В Windows-пакете отсутствует папка server-assets.");
        return path;
    }

    private static string RequireFile(string path)
    {
        if (!File.Exists(path))
            throw new FileNotFoundException($"Отсутствует файл для установки сервера: {Path.GetFileName(path)}", path);
        return path;
    }

    private static void EnsureSuccess(CommandResult result, string message)
    {
        if (result.ExitCode == 0) return;
        var details = string.IsNullOrWhiteSpace(result.Error) ? result.Output : result.Error;
        details = details.Trim();
        throw new InvalidOperationException(details.Length == 0 ? $"{message} (код {result.ExitCode})" : $"{message} (код {result.ExitCode}): {details}");
    }

    private static string TrimForLog(string prefix, string text)
    {
        var normalized = text.Trim();
        if (normalized.Length > 12000) normalized = normalized[^12000..];
        return prefix + normalized;
    }

    private static void Validate(AppSettings settings, bool requireServerPasswords)
    {
        if (string.IsNullOrWhiteSpace(settings.SshHost)) throw new ArgumentException("Укажите адрес VPS/SSH host.");
        if (string.IsNullOrWhiteSpace(settings.SshUser)) throw new ArgumentException("Укажите SSH user.");
        if (settings.SshPort is < 1 or > 65535) throw new ArgumentException("Некорректный SSH port.");
        if (settings.ServerPeerPort is < 1 or > 65535) throw new ArgumentException("Некорректный peer port.");
        if (settings.ServerWebPort is < 1 or > 65535) throw new ArgumentException("Некорректный web port.");
        if (string.IsNullOrWhiteSpace(settings.SshPrivateKeyPath) && string.IsNullOrEmpty(settings.SshPassword))
            throw new ArgumentException("Укажите SSH-пароль или приватный ключ.");
        if (requireServerPasswords)
        {
            if (string.IsNullOrEmpty(settings.ServerMainPassword)) throw new ArgumentException("Укажите основной пароль VPNSL.");
            if (string.IsNullOrWhiteSpace(settings.ServerWebLogin)) throw new ArgumentException("Укажите логин web-панели.");
            if (string.IsNullOrEmpty(settings.ServerWebPassword)) throw new ArgumentException("Укажите пароль web-панели.");
        }
    }

    private sealed record CommandResult(int ExitCode, string Output, string Error);
}
