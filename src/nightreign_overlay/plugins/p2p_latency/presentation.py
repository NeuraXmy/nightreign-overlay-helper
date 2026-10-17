"""Localized display text without changing helper protocol records."""

from collections.abc import Callable

from nightreign_overlay.plugins.p2p_latency.models import P2PStatus


def status_message(status: P2PStatus, tr: Callable[..., str]) -> str:
    """Translate known states and preserve messages from newer helpers as a fallback."""
    state = "simulated" if status.state == "steam_ready" and status.etw_state == "simulated" else status.state
    key = f"status.{state}"
    message = tr(key)
    return status.message if message == key else message
