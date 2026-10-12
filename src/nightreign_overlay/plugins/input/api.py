"""Public global-hotkey contract."""

from __future__ import annotations

from collections.abc import Callable


class HotkeyApi:
    """Registers callbacks using canonical combinations such as ``ctrl+shift+m``."""

    def register(self, action_id: str, default_combo: str, callback: Callable[[], None]) -> None:
        raise NotImplementedError

    def unregister(self, action_id: str) -> None:
        raise NotImplementedError

    def trigger_for_test(self, combo: str) -> None:
        """Inject a combination without a physical input device."""
        raise NotImplementedError
