"""Global hotkey provider; external input libraries are optional until a real device is used."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.input.api import HotkeyApi
from nightreign_overlay.plugins.input.config import InputConfig
from nightreign_overlay.ui.components import ConfigSwitchCard, SettingSection, SettingsPanel


class _HotkeyService(QObject, HotkeyApi):
    comboPressed = pyqtSignal(str)

    def __init__(self, config: InputConfig) -> None:
        super().__init__()
        self._config = config
        self._callbacks: dict[str, Callable[[], None]] = {}
        self.comboPressed.connect(self._dispatch)

    def register(self, action_id: str, default_combo: str, callback: Callable[[], None]) -> None:
        combo = _canonical_combo(self._config.bindings.value.get(action_id, default_combo))
        self._callbacks[action_id] = callback
        if self._config.bindings.value.get(action_id) != combo:
            self._config.bindings.set({**self._config.bindings.value, action_id: combo})

    def unregister(self, action_id: str) -> None:
        self._callbacks.pop(action_id, None)

    def trigger_for_test(self, combo: str) -> None:
        self.comboPressed.emit(_canonical_combo(combo))

    def _dispatch(self, combo: str) -> None:
        for action_id, callback in tuple(self._callbacks.items()):
            if self._config.bindings.value.get(action_id) == combo:
                callback()


class InputPlugin(Plugin):
    manifest = PluginManifest(
        id="input",
        kind=PluginKind.INFRASTRUCTURE,
        icon="GAME",
        settings_scope=SettingsScope.HIDDEN,
        order=10,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(InputConfig)
        self._listener: object | None = None
        self._service = _HotkeyService(self.config)

    def on_activate(self) -> None:
        self.ctx.provide(HotkeyApi, self._service)
        if self.config.enable_global_listener.value:
            self._start_keyboard_listener()
        self.ctx.on_cleanup(self._stop_listener)

    def on_deactivate(self) -> None:
        self._service._callbacks.clear()

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        panel = SettingsPanel(parent)
        section = SettingSection(self.ctx.tr("settings.title"))
        section.addCards(
            ConfigSwitchCard(
                self.config.enable_global_listener,
                FluentIcon.GAME,
                self.ctx.tr("settings.listener.title"),
                self.ctx.tr("settings.listener.content"),
            )
        )
        panel.addSection(section)
        return panel

    def _start_keyboard_listener(self) -> None:
        try:
            from pynput import keyboard
        except ImportError:
            self.ctx.log.warning("pynput is not installed; only HotkeyApi.trigger_for_test is available")
            return

        pressed: set[str] = set()

        def on_press(key: object) -> None:
            identifier = _pynput_identifier(key)
            if identifier is not None:
                pressed.add(identifier)
                self._service.comboPressed.emit("+".join(sorted(pressed)))

        def on_release(key: object) -> None:
            identifier = _pynput_identifier(key)
            if identifier is not None:
                pressed.discard(identifier)

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()

    def _stop_listener(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


def _canonical_combo(combo: str) -> str:
    keys = [part.strip().lower() for part in combo.split("+") if part.strip()]
    if not keys:
        raise ValueError("a hotkey must contain at least one key")
    return "+".join(sorted(set(keys)))


def _pynput_identifier(key: object) -> str | None:
    name = getattr(key, "name", None)
    if isinstance(name, str):
        return name.removesuffix("_l").removesuffix("_r")
    char = getattr(key, "char", None)
    return char.lower() if isinstance(char, str) and len(char) == 1 else None
