using System.Net;
using Microsoft.Diagnostics.Tracing.Parsers;
using Microsoft.Diagnostics.Tracing.Parsers.Kernel;
using Microsoft.Diagnostics.Tracing.Session;

namespace NightreignP2PHelper;

internal sealed class EtwPingMonitor : IDisposable
{
    private readonly object _gate = new();
    private readonly Dictionary<ulong, PingAccumulator> _pings = new();
    private readonly Dictionary<ulong, ulong> _targets = new();
    private TraceEventSession? _session;
    private Thread? _eventThread;

    public void Start()
    {
        if (!(TraceEventSession.IsElevated() ?? false))
            throw new UnauthorizedAccessException("ETW 网络跟踪需要管理员权限");

        // ETW sessions are machine-wide. Never use/restart the shared
        // "NT Kernel Logger" session because another profiler may own it.
        // Nightreign requires Windows 10+, where system providers support
        // independently named real-time kernel sessions.
        var sessionName = $"NightreignOverlayEtwKernel-{Environment.ProcessId}-{Guid.NewGuid():N}";
        _session = new TraceEventSession(
            sessionName,
            TraceEventSessionOptions.Create | TraceEventSessionOptions.NoRestartOnCreate)
        {
            StopOnDispose = true,
        };
        _session.EnableKernelProvider(KernelTraceEventParser.Keywords.NetworkTCPIP);
        _session.Source.Kernel.UdpIpSend += OnUdpSend;
        _session.Source.Kernel.UdpIpRecv += OnUdpReceive;

        _eventThread = new Thread(() => _session.Source.Process())
        {
            IsBackground = true,
            Name = "Nightreign ETW network events",
        };
        _eventThread.Start();
    }

    public void SyncTargets(IReadOnlyDictionary<ulong, ulong> targets)
    {
        lock (_gate)
        {
            _targets.Clear();
            foreach (var target in targets)
                _targets[target.Key] = target.Value;

            var requested = targets.Values.ToHashSet();
            foreach (var endpoint in _pings.Keys.Where(endpoint => !requested.Contains(endpoint)).ToArray())
                _pings.Remove(endpoint);
            foreach (var endpoint in requested)
                _pings.TryAdd(endpoint, new PingAccumulator());
        }
    }

    public EtwPeerMetrics? GetMetrics(ulong steamId)
    {
        lock (_gate)
        {
            return _targets.TryGetValue(steamId, out var endpoint)
                && _pings.TryGetValue(endpoint, out var ping)
                    ? ping.Snapshot()
                    : null;
        }
    }

    private void OnUdpSend(UdpIpTraceData packet)
    {
        var endpoint = ToEndpointKey(packet.daddr, packet.dport);
        lock (_gate)
        {
            if (!_pings.TryGetValue(endpoint, out var ping))
                return;
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            ping.ObserveTraffic(now);
            if (packet.size == 56)
                ping.ObserveStunSend(packet.TimeStampRelativeMSec, now);
        }
    }

    private void OnUdpReceive(UdpIpTraceData packet)
    {
        var endpoint = ToEndpointKey(packet.saddr, packet.sport);
        lock (_gate)
        {
            if (!_pings.TryGetValue(endpoint, out var ping))
                return;
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            ping.ObserveTraffic(now);
            if (packet.size == 68)
                ping.ObserveStunReceive(packet.TimeStampRelativeMSec, now);
        }
    }

    internal static ulong ToEndpointKey(IPAddress address, int port)
    {
        var bytes = address.MapToIPv4().GetAddressBytes();
        var ipv4 = BitConverter.ToUInt32(bytes, 0);
        return ((ulong)(ushort)port << 32) | ipv4;
    }

    public void Dispose()
    {
        var session = Interlocked.Exchange(ref _session, null);
        if (session is null)
            return;
        try
        {
            session.Source.StopProcessing();
            session.Stop();
        }
        catch
        {
            // The session may already have been stopped by Windows or another tracer.
        }
        finally
        {
            session.Dispose();
            _eventThread?.Join(TimeSpan.FromSeconds(2));
            _eventThread = null;
            lock (_gate)
            {
                _targets.Clear();
                _pings.Clear();
            }
        }
    }
}
