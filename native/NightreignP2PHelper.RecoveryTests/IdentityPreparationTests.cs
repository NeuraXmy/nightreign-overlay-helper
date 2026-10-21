using NightreignP2PHelper;

internal static class IdentityPreparationTests
{
    private static void Assert(bool ok, string reason) { if (!ok) throw new Exception(reason); }
    internal static void Run(Action<string, Action> test)
    {
        test("numeric and redirected vanity profiles remain inspectable", () => {
            Assert(IdentityProfileAddress.IsCandidate("https://steamcommunity.com/profiles/76561198049468923/?nr_identity=abc", "76561198049468923"), "numeric rejected");
            Assert(IdentityProfileAddress.IsCandidate("https://steamcommunity.com/id/teammate/?nr_identity=abc", "76561198049468923"), "vanity redirect rejected");
        });
        test("untrusted origins wrong numeric targets and nonprofile paths rejected", () => {
            foreach (var url in new[] { "http://steamcommunity.com/id/player/", "https://steamcommunity.com.evil.test/id/player/",
                "https://steamcommunity.com:4433/id/player/", "https://evil@steamcommunity.com/id/player/",
                "https://steamcommunity.com/profiles/76561198049468924/", "https://steamcommunity.com/login/",
                "https://steamcommunity.com/id/player/friends/" })
                Assert(!IdentityProfileAddress.IsCandidate(url, "76561198049468923"), "unsafe candidate accepted");
        });
        test("preflight timeout retries then blocks only once after success", () => {
            int reads = 0, blocks = 0, waited = 0; var retries = new List<int>();
            var ready = IdentityPreparation.Run(() => {
                if (++reads < 3) throw new IdentityPreparationException("page_timeout", "timeout", true);
                return true;
            }, () => { }, ms => waited += ms, (n, _) => retries.Add(n));
            if (ready) blocks++;
            Assert(reads == 3 && blocks == 1 && waited == 6000 && retries.SequenceEqual(new[] { 2, 3 }), "retry or mutation count");
        });
        test("permanent page failure stops at three attempts without mutation", () => {
            int reads = 0, blocks = 0;
            try {
                IdentityPreparation.Run<bool>(() => { reads++; throw new IdentityPreparationException("page_timeout", "timeout", true); },
                    () => { }, _ => { }, (_, _) => { });
                blocks++;
            } catch (IdentityPreparationException e) { Assert(e.Code == "page_timeout", "lost reason"); }
            Assert(reads == 3 && blocks == 0, "unbounded retry or mutation");
        });
        test("cancellation during backoff prevents another browser attempt", () => {
            int reads = 0; bool cancelled = false;
            try {
                IdentityPreparation.Run<bool>(() => { reads++; throw new IdentityPreparationException("browser_start", "timeout", true); },
                    () => { if (cancelled) throw new IdentityPreparationException("prepare_cancelled", "cancelled"); },
                    _ => cancelled = true, (_, _) => { });
                throw new Exception("cancellation ignored");
            } catch (IdentityPreparationException e) { Assert(e.Code == "prepare_cancelled" && reads == 1, "retried cancellation"); }
        });
        test("friend departure and account rejection cannot retry", () => {
            foreach (var code in new[] { "relationship_excluded", "peer_departed", "steam_account", "prepare_cancelled" }) {
                int reads = 0;
                try {
                    IdentityPreparation.Run(() => ++reads, () => { throw new IdentityPreparationException(code, "denied"); },
                        _ => throw new Exception("waited"), (_, _) => throw new Exception("retried"));
                    throw new Exception("accepted");
                } catch (IdentityPreparationException e) { Assert(e.Code == code && reads == 0, "opened browser despite rejection"); }
            }
        });
        test("wrong account and existing block never retry or change", () => {
            foreach (var page in new[] { new IdentityPage(false, true, false, false),
                                        new IdentityPage(true, false, true, false),
                                        new IdentityPage(true, true, true, false) }) {
                int reads = 0;
                try {
                    IdentityPreparation.Run(() => { reads++; IdentityPreparation.ValidatePage(page); return true; },
                        () => { }, _ => throw new Exception("waited"), (_, _) => throw new Exception("retried"));
                    throw new Exception("unsafe page accepted");
                } catch (IdentityPreparationException e) { Assert(!e.Retryable && reads == 1, "unsafe retry"); }
            }
        });
        test("incomplete page can load on the next read", () => {
            int reads = 0;
            IdentityPreparation.Run(() => {
                IdentityPreparation.ValidatePage(new(true, ++reads > 1, false, false)); return true;
            }, () => { }, _ => { }, (_, e) => Assert(e.Code == "page_controls", "wrong reason"));
            Assert(reads == 2, "incomplete page not retried");
        });
        test("unexpected or disk error is never a retry permission", () => {
            int reads = 0;
            try {
                IdentityPreparation.Run<bool>(() => { reads++; throw new IOException("disk"); },
                    () => { }, _ => throw new Exception("waited"), (_, _) => throw new Exception("retried"));
            } catch (IOException) { }
            Assert(reads == 1, "unknown failure retried");
        });
        test("second teammate retries independently of first completed preparation", () => {
            int first = 0, second = 0;
            IdentityPreparation.Run(() => ++first, () => { }, _ => { }, (_, _) => { });
            IdentityPreparation.Run(() => {
                if (++second == 1) throw new IdentityPreparationException("page_timeout", "timeout", true);
                return second;
            }, () => { }, _ => { }, (_, _) => { });
            Assert(first == 1 && second == 2, "one target restarted the other");
        });
    }
}
