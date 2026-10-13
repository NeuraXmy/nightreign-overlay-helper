namespace NightreignP2PHelper;

internal sealed record EtwPeerMetrics(
    int? PingMs,
    double? Quality,
    long? FirstPacketUnixMs,
    long? LastPacketUnixMs,
    int SampleCount);

/// <summary>
/// Computes old SteamNetworking RTT and quality from matching UDP/STUN events.
/// Adapted from SteamP2PInfo's MIT-licensed ETWPingMonitor.
/// </summary>
internal sealed class PingAccumulator
{
    internal const int MaximumSamples = 10;
    private readonly Queue<double> _samples = new(MaximumSamples);
    private double? _pendingSendTimestampMs;
    private double? _firstSendTimestampMs;
    private double? _lastPingMs;

    public long? FirstPacketUnixMs { get; private set; }
    public long? LastPacketUnixMs { get; private set; }

    public void ObserveTraffic(long unixTimeMs)
    {
        FirstPacketUnixMs ??= unixTimeMs;
        LastPacketUnixMs = unixTimeMs;
    }

    public void ObserveStunSend(double traceTimestampMs, long unixTimeMs)
    {
        ObserveTraffic(unixTimeMs);
        _firstSendTimestampMs ??= traceTimestampMs;

        // SteamP2PInfo observed dropped setup packets during the first 10 seconds.
        // During that warm-up period the newest send is the safest match. Afterwards
        // retain the outstanding send until a response arrives instead of producing
        // artificially tiny pings from a later request.
        if (_pendingSendTimestampMs is null || traceTimestampMs - _firstSendTimestampMs.Value < 10_000)
            _pendingSendTimestampMs = traceTimestampMs;
    }

    public void ObserveStunReceive(double traceTimestampMs, long unixTimeMs)
    {
        ObserveTraffic(unixTimeMs);
        if (_pendingSendTimestampMs is null)
            return;

        var ping = traceTimestampMs - _pendingSendTimestampMs.Value;
        _pendingSendTimestampMs = null;
        if (ping < 0 || ping > 30_000)
            return;

        _lastPingMs = ping;
        _samples.Enqueue(ping);
        while (_samples.Count > MaximumSamples)
            _samples.Dequeue();
    }

    public EtwPeerMetrics Snapshot()
    {
        double? quality = null;
        if (_samples.Count >= 3)
        {
            var average = _samples.Average();
            var jitter = Math.Sqrt(_samples.Average(sample => Math.Pow(sample - average, 2)));
            quality = Math.Clamp(1d / (0.01d * jitter + 1d), 0d, 1d);
        }

        return new EtwPeerMetrics(
            _lastPingMs is null ? null : Math.Max(0, (int)Math.Round(_lastPingMs.Value)),
            quality,
            FirstPacketUnixMs,
            LastPacketUnixMs,
            _samples.Count);
    }
}
