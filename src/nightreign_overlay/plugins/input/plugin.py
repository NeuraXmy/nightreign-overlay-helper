"""Global hotkey provider; external input libraries are optional until a real device is used."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding, InputDevice, InputStateListener
from nightreign_overlay.plugins.input.config import InputConfig
from nightreign_overlay.ui.components import ConfigSwitchCard, SettingSection, SettingsPanel

#: Seconds after which a held input is force-released; guards against release events lost on focus change.
MAX_PRESS_DURATION = 20.0
#: Legacy mouse filter: the primary buttons are used for normal play and never form a shortcut.
_IGNORED_MOUSE_BUTTONS = frozenset({"left", "right"})
#: SDL axis indices of the analog triggers on XInput-style controllers, reported as buttons.
_TRIGGER_AXES = {4: "lt", 5: "rt"}
_TRIGGER_THRESHOLD = 0.5
#: Directions of the first hat (D-pad), reported as buttons; diagonals and centre release all of them.
_HAT_DIRECTIONS = {(1, 0): "dpad_right", (-1, 0): "dpad_left", (0, -1): "dpad_down", (0, 1): "dpad_up"}


@dataclass
class _PressedInput:
    identifier: str
    time: float


class _HotkeyService(QObject, HotkeyApi):
    #: ``(device, keys in press order, pressed)``; ``pressed`` is False for a release snapshot.
    inputStateChanged = pyqtSignal(object, object, bool)

    def __init__(self, config: InputConfig) -> None:
        super().__init__()
        self._config = config
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._capture_listeners: set[InputStateListener] = set()
        self.inputStateChanged.connect(self._dispatch)

    def register(self, action_id: str, default: HotkeyBinding, callback: Callable[[], None]) -> None:
        binding = self.binding(action_id, default)
        self._callbacks[action_id] = callback
        if self._config.bindings.value.get(action_id) != _serialize_binding(binding):
            self.set_binding(action_id, binding)

    def unregister(self, action_id: str) -> None:
        self._callbacks.pop(action_id, None)

    def binding(self, action_id: str, default: HotkeyBinding) -> HotkeyBinding:
        return _parse_binding(self._config.bindings.value.get(action_id), default)

    def set_binding(self, action_id: str, binding: HotkeyBinding) -> None:
        self._config.bindings.set({**self._config.bindings.value, action_id: _serialize_binding(binding)})

    def subscribe_capture(self, listener: InputStateListener) -> None:
        self._capture_listeners.add(listener)

    def unsubscribe_capture(self, listener: InputStateListener) -> None:
        self._capture_listeners.discard(listener)

    def trigger_for_test(self, device: InputDevice, keys: tuple[str, ...]) -> None:
        self.inputStateChanged.emit(device, tuple(keys), True)

    def _dispatch(self, device: InputDevice, keys: tuple[str, ...], pressed: bool) -> None:
        canonical = _canonical_keys(keys)
        for listener in tuple(self._capture_listeners):
            listener(device, canonical)
        # Recording must be isolated from active hotkeys: a user can safely press an
        # existing binding while replacing it without triggering its business action.
        # Like the legacy tool, only a press can trigger; releasing part of a chord must not.
        if self._capture_listeners or not pressed or not keys:
            return
        for action_id, callback in tuple(self._callbacks.items()):
            binding = self.binding(action_id, HotkeyBinding(None))
            if binding.device == device and _matches_suffix(binding.keys, keys):
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
        self._keyboard_listener: object | None = None
        self._mouse_listener: object | None = None
        self._joystick_timer = QTimer(self)
        self._joystick_timer.setInterval(100)
        self._joystick_timer.timeout.connect(self._poll_joysticks)
        self._pygame: Any | None = None
        self._joysticks: dict[int, Any] = {}
        self._polling_joysticks = False
        self._pressed_keyboard: list[_PressedInput] = []
        self._pressed_mouse: list[_PressedInput] = []
        self._pressed_joystick: dict[int, list[_PressedInput]] = {}
        self._service = _HotkeyService(self.config)
        # Plugin pages are built before activation; their shortcut controls need this configuration API.
        self.ctx.provide(HotkeyApi, self._service)

    def on_activate(self) -> None:
        if self.config.enable_global_listener.value:
            self._start_keyboard_listener()
        self.ctx.on_cleanup(self._stop_listeners)

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
            from pynput import keyboard, mouse
        except ImportError:
            self.ctx.log.warning("pynput is not installed; physical keyboard and mouse input are unavailable")
        else:
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_keyboard_press,
                on_release=self._on_keyboard_release,
            )
            self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
            self._keyboard_listener.start()
            self._mouse_listener.start()
        self._start_joystick_polling()

    def _on_keyboard_press(self, key: object) -> None:
        identifier = _pynput_identifier(key)
        if identifier is not None:
            self._press(InputDevice.KEYBOARD, self._pressed_keyboard, identifier)

    def _on_keyboard_release(self, key: object) -> None:
        identifier = _pynput_identifier(key)
        if identifier is not None:
            self._release(InputDevice.KEYBOARD, self._pressed_keyboard, identifier)

    def _on_mouse_click(self, _x: int, _y: int, button: object, pressed: bool) -> None:
        identifier = getattr(button, "name", None)
        if not isinstance(identifier, str) or identifier in _IGNORED_MOUSE_BUTTONS:
            return
        if pressed:
            self._press(InputDevice.MOUSE, self._pressed_mouse, identifier)
        else:
            self._release(InputDevice.MOUSE, self._pressed_mouse, identifier)

    def _press(self, device: InputDevice, inputs: list[_PressedInput], identifier: str) -> None:
        now = time.monotonic()
        for item in inputs[:]:
            if now - item.time > MAX_PRESS_DURATION:
                inputs.remove(item)
                self.ctx.log.warning("Auto-released %s %r due to timeout", device.value, item.identifier)
        # Auto-repeat of a held key is not a new press and must not re-trigger its shortcut.
        if any(item.identifier == identifier for item in inputs):
            return
        inputs.append(_PressedInput(identifier, now))
        self._emit_input_state(device, inputs, pressed=True)

    def _release(self, device: InputDevice, inputs: list[_PressedInput], identifier: str) -> None:
        for item in inputs:
            if item.identifier == identifier:
                inputs.remove(item)
                self._emit_input_state(device, inputs, pressed=False)
                return

    def _start_joystick_polling(self) -> None:
        # Must be set before the import; otherwise pygame prints its banner to stdout.
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
        except ImportError:
            self.ctx.log.warning("pygame is not installed; controller input is unavailable")
            return
        pygame.init()
        pygame.joystick.init()
        self._pygame = pygame
        self._joystick_timer.start()

    def _scan_joysticks(self, pygame: Any) -> None:
        """Open newly connected controllers; SDL only reports button events for opened joysticks."""
        count = pygame.joystick.get_count()
        if count == len(self._joysticks):
            return
        self._joysticks.clear()
        for index in range(count):
            try:
                joystick = pygame.joystick.Joystick(index)
                joystick.init()
            except pygame.error as error:
                self.ctx.log.error("Could not initialize joystick %d: %s", index, error)
                continue
            self._joysticks[index] = joystick
            self.ctx.log.info("Detected Joystick %d: %s", index, joystick.get_name())

    def _poll_joysticks(self) -> None:
        pygame = self._pygame
        if pygame is None:
            return
        # On macOS SDL pumps the Cocoa event queue here, so Qt slots (including application
        # shutdown) can run inside ``event.get``; ``_stop_listeners`` then defers ``pygame.quit``.
        self._polling_joysticks = True
        try:
            self._scan_joysticks(pygame)
            events = pygame.event.get()
        except pygame.error as error:
            self.ctx.log.warning("Controller polling failed: %s", error)
            events = []
        finally:
            self._polling_joysticks = False
        if self._pygame is None:
            pygame.quit()
            return
        for event in events:
            self._handle_joystick_event(pygame, event)

    def _handle_joystick_event(self, pygame: Any, event: Any) -> None:
        # Each controller keeps its own combination, so two pads never form a chord together.
        if event.type not in (
            pygame.JOYBUTTONDOWN,
            pygame.JOYBUTTONUP,
            pygame.JOYAXISMOTION,
            pygame.JOYHATMOTION,
        ):
            return
        inputs = self._pressed_joystick.setdefault(event.joy, [])
        if event.type == pygame.JOYBUTTONDOWN:
            self._press(InputDevice.JOYSTICK, inputs, f"button_{event.button}")
        elif event.type == pygame.JOYBUTTONUP:
            self._release(InputDevice.JOYSTICK, inputs, f"button_{event.button}")
        elif event.type == pygame.JOYAXISMOTION:
            trigger = _TRIGGER_AXES.get(event.axis)
            if trigger is not None and event.value > _TRIGGER_THRESHOLD:
                self._press(InputDevice.JOYSTICK, inputs, trigger)
            elif trigger is not None and event.value <= -_TRIGGER_THRESHOLD:
                self._release(InputDevice.JOYSTICK, inputs, trigger)
        elif event.hat == 0:
            direction = _HAT_DIRECTIONS.get(tuple(event.value))
            if direction is not None:
                self._press(InputDevice.JOYSTICK, inputs, direction)
            else:
                for released in _HAT_DIRECTIONS.values():
                    self._release(InputDevice.JOYSTICK, inputs, released)

    def _emit_input_state(self, device: InputDevice, inputs: list[_PressedInput], *, pressed: bool) -> None:
        keys = tuple(item.identifier for item in inputs)
        self._service.inputStateChanged.emit(device, keys, pressed)

    def _stop_listeners(self) -> None:
        self._joystick_timer.stop()
        for attribute in ("_keyboard_listener", "_mouse_listener"):
            listener = getattr(self, attribute)
            if listener is not None:
                listener.stop()
                setattr(self, attribute, None)
        if self._pygame is not None:
            self._joysticks.clear()
            if not self._polling_joysticks:
                self._pygame.quit()
            self._pygame = None
        self._pressed_keyboard.clear()
        self._pressed_mouse.clear()
        self._pressed_joystick.clear()


def _canonical_keys(keys: tuple[str, ...] | set[str] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({key.strip().lower() for key in keys if key.strip()}, key=_key_sort_key))


def _matches_suffix(binding: tuple[str, ...], pressed: tuple[str, ...]) -> bool:
    """Legacy suffix match: the most recent presses form the binding; keys held before are ignored."""
    if not binding or len(pressed) < len(binding):
        return False
    return _canonical_keys(pressed[-len(binding) :]) == binding


def _key_sort_key(key: str) -> tuple[int, str]:
    order = {"ctrl": 0, "alt": 1, "shift": 2, "cmd": 3}
    return order.get(key, 10), key


def _parse_binding(raw: object, default: HotkeyBinding) -> HotkeyBinding:
    if raw is None:
        return default
    if isinstance(raw, str):
        return HotkeyBinding(InputDevice.KEYBOARD, _canonical_keys(raw.split("+")))
    if not isinstance(raw, dict):
        return default
    try:
        device = InputDevice(raw.get("device")) if raw.get("device") is not None else None
        keys = raw.get("keys", [])
        return HotkeyBinding(device, _canonical_keys(keys) if isinstance(keys, list) else ())
    except ValueError:
        return default


def _serialize_binding(binding: HotkeyBinding) -> dict[str, object]:
    return {
        "device": binding.device.value if binding.device is not None else None,
        "keys": list(binding.keys),
    }


def _pynput_identifier(key: object) -> str | None:
    name = getattr(key, "name", None)
    if isinstance(name, str):
        identifier = name.removesuffix("_l").removesuffix("_r")
        # pynput calls the physical Command key ``cmd`` on macOS; keep that identity
        # independent from any Cmd/Ctrl logical remapping configured by the operating system.
        return "cmd" if identifier in {"cmd", "meta"} else identifier
    char = getattr(key, "char", None)
    if not isinstance(char, str) or len(char) != 1 or ord(char) >= 128:
        return None
    # With Ctrl held, Windows reports letters as ASCII control characters (Ctrl+A -> "\x01").
    if 1 <= ord(char) <= 26:
        return chr(ord(char) + 96)
    return char.lower()
