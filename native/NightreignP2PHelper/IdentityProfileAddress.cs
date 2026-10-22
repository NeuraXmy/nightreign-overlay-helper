using System.Text.RegularExpressions;

namespace NightreignP2PHelper;

// URL shape is only a candidate. DOM inspection must separately prove the
// profile SteamID, active account and current navigation token before mutation.
internal static class IdentityProfileAddress
{
    internal static bool IsCandidate(string value, string target)
        => Uri.TryCreate(value, UriKind.Absolute, out var uri)
        && uri.Scheme == "https" && uri.Host == "steamcommunity.com" && uri.IsDefaultPort
        && string.IsNullOrEmpty(uri.UserInfo)
        && (uri.AbsolutePath == "/profiles/" + target + "/"
            || Regex.IsMatch(uri.AbsolutePath, @"^/id/[^/]+/?$"));
}
