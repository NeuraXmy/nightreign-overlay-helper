using System.Diagnostics;
using System.Text.Json;
using Steamworks;

namespace NightreignP2PHelper;

// A single owned Steam browser. Session cookies and HTML never leave this surface.
// No block/unblock implementation is included in this migration.
internal sealed class SteamCommentSession : ICommentPage
{
    private readonly string account, target;
    private readonly Action ensureActive;
    private readonly List<IDisposable> callbacks = new();
    private readonly Stopwatch clock = Stopwatch.StartNew();
    private HHTMLBrowser browser;
    private bool initialized;
    private string token = "";
    private bool? inspected;
    private string? outcome;
    private long nextProbe;

    internal SteamCommentSession(string account, string target, Action ensureActive)
    {
        this.account = account; this.target = target; this.ensureActive = ensureActive;
        if (!SteamHTMLSurface.Init()) throw new InvalidOperationException("Steam HTML unavailable");
        initialized = true;
        try
        {
            callbacks.Add(Callback<HTML_StartRequest_t>.Create(x => {
                if (Owns(x.unBrowserHandle)) SteamHTMLSurface.AllowStartRequest(x.unBrowserHandle, Allowed(x.pchURL));
            }));
            callbacks.Add(Callback<HTML_JSAlert_t>.Create(x => { if (Owns(x.unBrowserHandle)) SteamHTMLSurface.JSDialogResponse(browser, false); }));
            callbacks.Add(Callback<HTML_JSConfirm_t>.Create(x => { if (Owns(x.unBrowserHandle)) SteamHTMLSurface.JSDialogResponse(browser, false); }));
            callbacks.Add(Callback<HTML_FileOpenDialog_t>.Create(x => { if (Owns(x.unBrowserHandle)) SteamHTMLSurface.FileLoadDialogResponse(browser, IntPtr.Zero); }));
            callbacks.Add(Callback<HTML_ChangedTitle_t>.Create(OnTitle));
            bool ready = false;
            using var result = CallResult<HTML_BrowserReady_t>.Create((x, failed) => {
                if (!failed) browser = x.unBrowserHandle;
                ready = true;
            });
            result.Set(SteamHTMLSurface.CreateBrowser("NightreignCommendation/1", null));
            Pump(() => ready, 15000);
            if (browser == HHTMLBrowser.Invalid) throw new TimeoutException();
            SteamHTMLSurface.SetSize(browser, 1024, 768);
        }
        catch { Dispose(); throw; }
    }

    private bool Owns(HHTMLBrowser handle) => browser != HHTMLBrowser.Invalid && handle == browser;
    internal static bool Allowed(string value) => Uri.TryCreate(value, UriKind.Absolute, out var uri)
        && uri.Scheme == "https" && uri.IsDefaultPort && string.IsNullOrEmpty(uri.UserInfo)
        && uri.Host is "steamcommunity.com" or "store.steampowered.com" or "login.steampowered.com";

    private string ProfileGuard => $$"""
        location.origin==='https://steamcommunity.com' &&
        (location.pathname==='/profiles/{{target}}/'||/^\/id\/[^/]+\/?$/.test(location.pathname)) &&
        String(window.g_rgProfileData?.steamid||'')==='{{target}}'
        """;
    private string Guard => $$"""
        ({{ProfileGuard}}) && String(window.g_steamID||'')==='{{account}}' &&
        typeof window.g_sessionID==='string' && location.search==='?nr_commend={{token}}'
        """;

    public bool Inspect()
    {
        ensureActive();
        token = Guid.NewGuid().ToString("N");
        inspected = null;
        nextProbe = clock.ElapsedMilliseconds + 400;
        SteamHTMLSurface.LoadURL(browser, "https://steamcommunity.com/profiles/" + target + "/?nr_commend=" + token, null);
        Pump(() => inspected.HasValue, 45000);
        nextProbe = 0;
        return inspected ?? throw new TimeoutException();
    }

    public string Post(string comment)
    {
        ensureActive();
        outcome = null;
        // Exactly one POST. The caller has already flushed the durable reservation.
        SteamHTMLSurface.ExecuteJavascript(browser, $$"""
            (async function(){
              const report=state=>document.title='NRCOMMENT:'+JSON.stringify({token:'{{token}}',state});
              if(!({{Guard}})){report('precondition');return;}
              const thread=Object.values(window.g_rgCommentThreads||{}).find(t=>
                t.m_strCommentThreadType==='Profile'&&String(t.m_rgCommentData.owner)==='{{target}}');
              if(!thread||!thread.m_elTextArea||thread.m_elTextArea.disabled){report('precondition');return;}
              const url=new URL(thread.GetActionURL('post'),location.origin);
              if(url.origin!=='https://steamcommunity.com'||url.pathname!=='/comment/Profile/post/{{target}}/-1/'){
                report('precondition');return;}
              try {
                const params=thread.ParametersWithDefaults({comment:{{JsonSerializer.Serialize(comment)}}});
                const r=await fetch(url.href,{method:'POST',credentials:'same-origin',
                  headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},
                  body:new URLSearchParams(params).toString()});
                const data=await r.json();
                report(data.success?'sent':'rejected');
              }catch(e){report('unknown');}
            })();
            """);
        Pump(() => outcome is not null, 20000);
        return outcome ?? "unknown";
    }

    private void Pump(Func<bool> done, int milliseconds)
    {
        var until = clock.ElapsedMilliseconds + milliseconds;
        while (!done() && clock.ElapsedMilliseconds < until)
        {
            ensureActive();
            SteamAPI.RunCallbacks();
            if (nextProbe > 0 && clock.ElapsedMilliseconds >= nextProbe)
            {
                nextProbe = clock.ElapsedMilliseconds + 400;
                SteamHTMLSurface.ExecuteJavascript(browser, $$"""
                    (function(){
                      if(!({{ProfileGuard}})||location.search!=='?nr_commend={{token}}'||document.readyState==='loading')return;
                      const ready=({{Guard}})&&!!document.querySelector('#account_pulldown')&&
                        !document.querySelector('[onclick*="ConfirmUnblock"],a[href*="ConfirmUnblock"]')&&
                        Object.values(window.g_rgCommentThreads||{}).some(t=>t.m_strCommentThreadType==='Profile'&&
                          String(t.m_rgCommentData.owner)==='{{target}}'&&t.m_elTextArea&&!t.m_elTextArea.disabled);
                      document.title='NRCOMMENT:'+JSON.stringify({token:'{{token}}',page:true,ready:!!ready});
                    })();
                    """);
            }
            Thread.Sleep(25);
        }
    }

    private void OnTitle(HTML_ChangedTitle_t message)
    {
        if (!Owns(message.unBrowserHandle) || !message.pchTitle.StartsWith("NRCOMMENT:", StringComparison.Ordinal)) return;
        try
        {
            using var document = JsonDocument.Parse(message.pchTitle[10..]);
            var root = document.RootElement;
            if (root.GetProperty("token").GetString() != token) return;
            if (root.TryGetProperty("page", out var page) && page.ValueKind == JsonValueKind.True)
                inspected = root.GetProperty("ready").ValueKind == JsonValueKind.True;
            else if (root.TryGetProperty("state", out var state))
                outcome = state.GetString();
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or KeyNotFoundException) { }
    }

    public void Dispose()
    {
        if (!initialized) return;
        initialized = false;
        try { if (browser != HHTMLBrowser.Invalid) SteamHTMLSurface.RemoveBrowser(browser); }
        finally
        {
            foreach (var callback in callbacks) callback.Dispose();
            callbacks.Clear();
            SteamHTMLSurface.Shutdown();
        }
    }
}
