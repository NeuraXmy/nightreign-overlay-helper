"""Public global-hotkey contract."""

from __future__ import annotations

from collections.abc import Callable

from nightreign_overlay.core.input import HotkeyBinding, InputDevice

InputStateListener = Callable[[InputDevice, tuple[str, ...]], None]


class HotkeyApi:
    """Registers callbacks using canonical combinations such as ``ctrl+shift+m``."""

    def register(self, action_id: str, default: HotkeyBinding, callback: Callable[[], None]) -> None:
        raise NotImplementedError

    def unregister(self, action_id: str) -> None:
        raise NotImplementedError

    def binding(self, action_id: str, default: HotkeyBinding) -> HotkeyBinding:
        """Return a persisted binding, migrating a legacy keyboard string when present."""
        raise NotImplementedError

    def set_binding(self, action_id: str, binding: HotkeyBinding) -> None:
        """Persist one new structured binding, or disable it with an empty binding."""
        raise NotImplementedError

    def subscribe_capture(self, listener: InputStateListener) -> None:
        """Receive live device states while a shortcut configuration dialog is open."""
        raise NotImplementedError

    def unsubscribe_capture(self, listener: InputStateListener) -> None:
        raise NotImplementedError

    def trigger_for_test(self, device: InputDevice, keys: tuple[str, ...]) -> None:
        """Inject an input state without physical hardware."""
        raise NotImplementedError
