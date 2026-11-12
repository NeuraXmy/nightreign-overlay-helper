"""Manual-recovery alerts stay visible and wait for a hidden window to return."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from qfluentwidgets import InfoBarPosition

from nightreign_overlay.app import Application
from nightreign_overlay.plugins.steam_recovery.api import RecoveryStopped


def test_recovery_alert_waits_for_window_and_deduplicates(qapp):
    owner = SimpleNamespace(
        _recovery_stop_seen=set(),
        _recovery_stop_notifications=set(),
        _shut_down=False,
        window=SimpleNamespace(is_present=False),
    )
    owner._show_recovery_stopped = lambda present: Application._show_recovery_stopped(owner, present)
    with patch("nightreign_overlay.app.InfoBar.error") as show:
        Application._on_recovery_stopped(owner, RecoveryStopped("a" * 32))
        Application._on_recovery_stopped(owner, RecoveryStopped("a" * 32))
        show.assert_not_called()
        owner.window.is_present = True
        owner._show_recovery_stopped(True)
        show.assert_called_once()
        assert show.call_args.kwargs["position"] == InfoBarPosition.TOP_RIGHT
        assert show.call_args.kwargs["duration"] == -1
        Application._on_recovery_stopped(owner, RecoveryStopped("a" * 32))
        owner._show_recovery_stopped(True)
        show.assert_called_once()


def test_recovery_alert_not_shown_during_shutdown(qapp):
    owner = SimpleNamespace(_recovery_stop_notifications={"a" * 32}, _shut_down=True, window=Mock())
    with patch("nightreign_overlay.app.InfoBar.error") as show:
        Application._show_recovery_stopped(owner, True)
        show.assert_not_called()
