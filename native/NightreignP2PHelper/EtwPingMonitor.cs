using System.Diagnostics;
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
        // ETW sessions are machine-wide. Never use/restart the shared
        // "NT Kernel Logger" session because another profiler may own it.
        // Nightreign requires Windows 10+, where system providers support
        // independently named real-time kernel sessions.
        CleanupStaleSessions();
        var sessionName = $"NightreignOverlayEtwKernel-{Environment.ProcessId}-{Guid.NewGuid():N}";
        var session = new TraceEventSession(
            sessionName,
            TraceEventSessionOptions.Create | TraceEventSessionOptions.NoRestartOnCreate)
        {
            StopOnDispose = true,
        };
        try
        {
            session.EnableKernelProvider(KernelTraceEventParser.Keywords.NetworkTCPIP);
            session.Source.Kernel.UdpIpSend += OnUdpSend;
            session.Source.Kernel.UdpIpRecv += OnUdpReceive;
            _session = session;
        }
        catch
        {
            session.Dispose();
            throw;
        }

        _eventThread = new Thread(() => session.Source.Process())
        {
            IsBackground = true,
            Name = "Nightreign ETW network events",
        };
        _eventThread.Start();
    }

    private static void CleanupStaleSessions()
    {
        const string prefix = "NightreignOverlayEtwKernel-";
        foreach (var name in TraceEventSession.GetActiveSessionNames())
        {
            if (!name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                continue;

            var separator = name.IndexOf('-', prefix.Length);
            if (separator < 0 || !int.TryParse(name.AsSpan(prefix.Length, separator - prefix.Length), out var processId))
                continue;

            try
            {
                using var process = Process.GetProcessById(processId);
                if (!process.HasExited)
                    continue;
            }
            catch (ArgumentException)
            {
                // The owning process no longer exists; the session is stale.
            }
            catch (InvalidOperationException)
            {
                // The process exited between lookup and HasExited.
            }

            try
            {
                using var stale = new TraceEventSession(name, TraceEventSessionOptions.Attach)
                {
                    StopOnDispose = true,
                };
                stale.Stop();
            }
            catch
            {
                // Another process may have reclaimed or stopped the session.
            }
        }
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
