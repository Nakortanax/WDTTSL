using System.ComponentModel;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;

namespace VPNSL.Windows;

internal sealed class WintunAdapter : IDisposable
{
    private const uint RingCapacity = 0x400000; // 4 MiB
    private const int SocketBufferBytes = 4 * 1024 * 1024;
    private const int ErrorNoMoreItems = 259;
    private const uint WaitTimeout = 258;

    private IntPtr _adapter;
    private IntPtr _session;
    private UdpClient? _udp;
    private CancellationTokenSource? _bridgeCancellation;
    private Task? _readTask;
    private Task? _writeTask;
    private long _tunToClientPackets;
    private long _clientToTunPackets;

    public uint InterfaceIndex { get; private set; }
    public long TunToClientPackets => Interlocked.Read(ref _tunToClientPackets);
    public long ClientToTunPackets => Interlocked.Read(ref _clientToTunPackets);

    public void Open()
    {
        if (_adapter != IntPtr.Zero) return;
        _adapter = WintunOpenAdapter("VPNSL");
        if (_adapter == IntPtr.Zero)
            _adapter = WintunCreateAdapter("VPNSL", "VPNSL", IntPtr.Zero);
        if (_adapter == IntPtr.Zero) throw LastError("Не удалось создать адаптер Wintun");

        WintunGetAdapterLUID(_adapter, out var luid);
        var status = ConvertInterfaceLuidToIndex(ref luid, out var index);
        if (status != 0) throw new Win32Exception((int)status, "Не удалось получить индекс Wintun");
        InterfaceIndex = index;

        _session = WintunStartSession(_adapter, RingCapacity);
        if (_session == IntPtr.Zero) throw LastError("Не удалось запустить сессию Wintun");
    }

    public void StartBridge(int clientPort, Action<string> log, CancellationToken parentToken)
    {
        if (_session == IntPtr.Zero) throw new InvalidOperationException("Wintun не запущен");
        if (_bridgeCancellation is not null) return;

        _bridgeCancellation = CancellationTokenSource.CreateLinkedTokenSource(parentToken);
        _udp = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
        _udp.Client.SendBufferSize = SocketBufferBytes;
        _udp.Client.ReceiveBufferSize = SocketBufferBytes;
        _udp.Connect(IPAddress.Loopback, clientPort);
        var token = _bridgeCancellation.Token;
        log($"[WINTUN] Локальный мост запущен → 127.0.0.1:{clientPort}");

        _readTask = Task.Run(
            () => RunPumpAsync("TUN→client", () => PumpTunToClientAsync(_udp, log, token), log, token),
            CancellationToken.None);
        _writeTask = Task.Run(
            () => RunPumpAsync("client→TUN", () => PumpClientToTunAsync(_udp, log, token), log, token),
            CancellationToken.None);
    }

    private static async Task RunPumpAsync(
        string name,
        Func<Task> pump,
        Action<string> log,
        CancellationToken token)
    {
        try
        {
            await pump().ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
        }
        catch (ObjectDisposedException) when (token.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            log($"[WINTUN] Мост {name} остановлен с ошибкой: {ex.Message}");
        }
    }

    private async Task PumpTunToClientAsync(UdpClient udp, Action<string> log, CancellationToken token)
    {
        var waitEvent = WintunGetReadWaitEvent(_session);
        if (waitEvent == IntPtr.Zero) throw LastError("WintunGetReadWaitEvent");

        while (!token.IsCancellationRequested)
        {
            var packet = WintunReceivePacket(_session, out var size);
            if (packet != IntPtr.Zero)
            {
                try
                {
                    if (size is > 0 and <= 0xFFFF)
                    {
                        var length = checked((int)size);
                        var managed = new byte[length];
                        Marshal.Copy(packet, managed, 0, length);
                        await udp.SendAsync(managed, token);
                        if (Interlocked.Increment(ref _tunToClientPackets) == 1)
                            log($"[WINTUN] Первый исходящий IP-пакет передан в client.exe ({length} байт)");
                    }
                }
                finally
                {
                    WintunReleaseReceivePacket(_session, packet);
                }
                continue;
            }

            var error = Marshal.GetLastWin32Error();
            if (error != ErrorNoMoreItems)
            {
                log($"[WINTUN] Ошибка чтения: {new Win32Exception(error).Message}");
                await Task.Delay(20, token);
                continue;
            }

            var wait = WaitForSingleObject(waitEvent, 250);
            if (wait != WaitTimeout && wait != 0)
                await Task.Delay(10, token);
        }
    }

    private async Task PumpClientToTunAsync(UdpClient udp, Action<string> log, CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            UdpReceiveResult result;
            try
            {
                result = await udp.ReceiveAsync(token);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                if (!token.IsCancellationRequested) log($"[WINTUN] Ошибка UDP: {ex.Message}");
                await Task.Delay(20, token);
                continue;
            }

            if (result.Buffer.Length == 0 || result.Buffer.Length > 0xFFFF) continue;
            var packet = WintunAllocateSendPacket(_session, checked((uint)result.Buffer.Length));
            if (packet == IntPtr.Zero)
            {
                var error = Marshal.GetLastWin32Error();
                log($"[WINTUN] Ошибка выделения пакета: {new Win32Exception(error).Message}");
                continue;
            }
            Marshal.Copy(result.Buffer, 0, packet, result.Buffer.Length);
            WintunSendPacket(_session, packet);
            if (Interlocked.Increment(ref _clientToTunPackets) == 1)
                log($"[WINTUN] Первый входящий IP-пакет получен от client.exe ({result.Buffer.Length} байт)");
        }
    }

    public void Dispose()
    {
        try { _bridgeCancellation?.Cancel(); } catch { }
        try { _udp?.Dispose(); } catch { }
        try
        {
            var tasks = new Task?[] { _readTask, _writeTask }
                .Where(task => task is not null)
                .Cast<Task>()
                .ToArray();
            if (tasks.Length > 0) Task.WaitAll(tasks, 1000);
        }
        catch { }
        _bridgeCancellation?.Dispose();
        _bridgeCancellation = null;
        _udp = null;

        if (_session != IntPtr.Zero)
        {
            WintunEndSession(_session);
            _session = IntPtr.Zero;
        }
        if (_adapter != IntPtr.Zero)
        {
            WintunCloseAdapter(_adapter);
            _adapter = IntPtr.Zero;
        }
    }

    private static Win32Exception LastError(string message)
    {
        var error = Marshal.GetLastWin32Error();
        return new Win32Exception(error, $"{message}: {new Win32Exception(error).Message}");
    }

    [DllImport("wintun.dll", CharSet = CharSet.Unicode, SetLastError = true, CallingConvention = CallingConvention.StdCall)]
    private static extern IntPtr WintunCreateAdapter(string name, string tunnelType, IntPtr requestedGuid);

    [DllImport("wintun.dll", CharSet = CharSet.Unicode, SetLastError = true, CallingConvention = CallingConvention.StdCall)]
    private static extern IntPtr WintunOpenAdapter(string name);

    [DllImport("wintun.dll", CallingConvention = CallingConvention.StdCall)]
    private static extern void WintunCloseAdapter(IntPtr adapter);

    [DllImport("wintun.dll", CallingConvention = CallingConvention.StdCall)]
    private static extern void WintunGetAdapterLUID(IntPtr adapter, out ulong luid);

    [DllImport("wintun.dll", SetLastError = true, CallingConvention = CallingConvention.StdCall)]
    private static extern IntPtr WintunStartSession(IntPtr adapter, uint capacity);

    [DllImport("wintun.dll", CallingConvention = CallingConvention.StdCall)]
    private static extern void WintunEndSession(IntPtr session);

    [DllImport("wintun.dll", CallingConvention = CallingConvention.StdCall)]
    private static extern IntPtr WintunGetReadWaitEvent(IntPtr session);

    [DllImport("wintun.dll", SetLastError = true, CallingConvention = CallingConvention.StdCall)]
    private static extern IntPtr WintunReceivePacket(IntPtr session, out uint packetSize);

    [DllImport("wintun.dll", CallingConvention = CallingConvention.StdCall)]
    private static extern void WintunReleaseReceivePacket(IntPtr session, IntPtr packet);

    [DllImport("wintun.dll", SetLastError = true, CallingConvention = CallingConvention.StdCall)]
    private static extern IntPtr WintunAllocateSendPacket(IntPtr session, uint capacity);

    [DllImport("wintun.dll", CallingConvention = CallingConvention.StdCall)]
    private static extern void WintunSendPacket(IntPtr session, IntPtr packet);

    [DllImport("iphlpapi.dll")]
    private static extern uint ConvertInterfaceLuidToIndex(ref ulong interfaceLuid, out uint interfaceIndex);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
}
