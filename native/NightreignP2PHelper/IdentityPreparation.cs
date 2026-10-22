namespace NightreignP2PHelper;

internal sealed class IdentityPreparationException(string code, string message, bool retryable = false)
    : Exception(message)
{
    internal string Code { get; } = code;
    internal bool Retryable { get; } = retryable;
}

// Only read-only preparation belongs in this driver. Journal writes, block POSTs
// and recovery are deliberately outside it, so a retry cannot repeat a mutation.
internal static class IdentityPreparation
{
    internal static T Run<T>(Func<T> prepare, Action validate, Action<int> wait,
        Action<int, IdentityPreparationException> retry, int attempts = 3)
    {
        if (attempts < 1) throw new ArgumentOutOfRangeException(nameof(attempts));
        for (int attempt = 1; ; attempt++)
        {
            validate();
            try { return prepare(); }
            catch (IdentityPreparationException failure) when (failure.Retryable && attempt < attempts)
            {
                retry(attempt + 1, failure);
                // Keep pumping recovery/IPC heartbeats and notice cancellation
                // during backoff, instead of waiting until the next browser opens.
                for (int elapsed = 0; elapsed < attempt * 2000; elapsed += 250)
                { wait(250); validate(); }
            }
        }
    }

    internal static void ValidatePage(IdentityPage page)
    {
        if (!page.CorrectAccount)
            throw new IdentityPreparationException("page_account", "Steam 网页未登录原账号，未修改通信状态");
        if (page.CanUnblock)
            throw new IdentityPreparationException("page_preblocked", "网页显示已屏蔽或通信状态冲突，未修改通信状态");
        if (!page.CanBlock)
            throw new IdentityPreparationException("page_controls", "Steam 网页通信菜单尚未就绪", true);
    }
}
