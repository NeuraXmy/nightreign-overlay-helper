"""Unit coverage for P2 infrastructure contracts that does not need input hardware."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PyQt6.QtCore import QEventLoop, QRect, QTimer
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import ForegroundPolicy
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.capture import plugin as capture_plugin
from nightreign_overlay.plugins.capture.api import hdr_to_sdr, make_frame
from nightreign_overlay.plugins.capture.plugin import CapturePlugin
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding, InputDevice
from nightreign_overlay.plugins.input.config import InputConfig
from nightreign_overlay.plugins.input.plugin import (
    MAX_PRESS_DURATION,
    InputPlugin,
    _HotkeyService,
    _pynput_identifier,
)
from nightreign_overlay.plugins.region.config import RegionConfig
from nightreign_overlay.ui.components.setting_cards import _format_binding, _HotkeySettingDialog


def _request_frame(plugin: CapturePlugin):
    result = []
    loop = QEventLoop()

    def done(frame):
        result.append(frame)
        loop.quit()

    plugin.request_frame(done)
    QTimer.singleShot(1000, loop.quit)
    loop.exec()
    assert result, "capture request timed out"
    return result[0]


def test_capture_frame_is_detached() -> None:
    source = QImage(4, 3, QImage.Format.Format_ARGB32)
    source.fill(0xFF112233)
    frame = make_frame(source)

    source.fill(0xFF000000)
    assert frame.image.pixelColor(0, 0).name() == "#112233"


def test_capture_frames_carry_the_shared_hdr_setting(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    services = ServiceRegistry()
    events = EventBus()
    services.register(ForegroundPolicy, SimpleNamespace(detection_allowed=True))
    plugin = CapturePlugin(PluginContext("capture", tmp_path, store, Translator("zh_CN"), services, events))
    plugin.on_load()
    source = QImage(4, 3, QImage.Format.Format_RGB32)
    source.fill(0xFF808080)
    monkeypatch.setattr(
        capture_plugin,
        "_MssCapture",
        lambda **_kwargs: SimpleNamespace(grab=lambda: source, close=lambda: None),
    )

    assert _request_frame(plugin).hdr is False
    plugin.config.hdr_processing.set(True)
    frame = _request_frame(plugin)
    assert frame.hdr is True
    # The shared frame stays raw; consumers decide how to process it.
    assert frame.image.pixelColor(0, 0).name() == "#808080"
    plugin.on_deactivate()


def test_capture_and_hotkeys_follow_the_foreground_policy(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    services = ServiceRegistry()
    policy = SimpleNamespace(detection_allowed=False, input_allowed=False)
    services.register(ForegroundPolicy, policy)
    capture = CapturePlugin(
        PluginContext("capture", tmp_path, store, Translator("zh_CN"), services, EventBus())
    )
    capture.on_load()
    source = QImage(4, 3, QImage.Format.Format_RGB32)
    monkeypatch.setattr(
        capture_plugin,
        "_MssCapture",
        lambda **_kwargs: SimpleNamespace(grab=lambda: source, close=lambda: None),
    )
    assert _request_frame(capture) is None
    policy.detection_allowed = True
    assert _request_frame(capture) is not None
    capture.on_deactivate()

    service = _HotkeyService(store.bind(InputConfig, "plugins.input"))
    service.foreground = policy
    fired: list[str] = []
    service.register("act", HotkeyBinding(InputDevice.KEYBOARD, ("f1",)), lambda: fired.append("act"))
    service.trigger_for_test(InputDevice.KEYBOARD, ("f1",))
    assert fired == []
    policy.input_allowed = True
    service.trigger_for_test(InputDevice.KEYBOARD, ("f1",))
    assert fired == ["act"]


def test_hdr_to_sdr_matches_legacy_gamma() -> None:
    pixels = np.array([[[0, 64, 255]]], dtype=np.uint8)
    assert hdr_to_sdr(pixels).tolist() == [[[0, 136, 255]]]


def test_capture_stream_runs_only_while_leased(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    services = ServiceRegistry()
    services.register(ForegroundPolicy, SimpleNamespace(detection_allowed=True))
    context = PluginContext(
        "capture",
        tmp_path,
        store,
        Translator("zh_CN"),
        services,
        EventBus(),
    )
    plugin = CapturePlugin(context)
    plugin.on_load()

    assert not plugin._timer.isActive()
    plugin.acquire_stream("day_timer")
    plugin.acquire_stream("day_timer")
    assert plugin._timer.isActive()

    plugin.release_stream("day_timer")
    assert plugin._timer.isActive()
    plugin.release_stream("day_timer")
    assert not plugin._timer.isActive()
    plugin.on_deactivate()


def test_input_exposes_hotkey_configuration_on_load(store: ConfigStore, tmp_path: Path) -> None:
    services = ServiceRegistry()
    context = PluginContext("input", tmp_path, store, Translator("zh_CN"), services, EventBus())
    plugin = InputPlugin(context)

    plugin.on_load()

    hotkeys = services.require(HotkeyApi)
    default = HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "d"))
    assert hotkeys.binding("day_timer.next_day", default) == default
    hotkeys.set_binding("day_timer.next_day", HotkeyBinding(InputDevice.KEYBOARD, ("alt", "d")))
    assert hotkeys.binding("day_timer.next_day", default) == HotkeyBinding(InputDevice.KEYBOARD, ("alt", "d"))


class _FakePygame:
    """Just enough of pygame for the polling loop; ``on_get`` runs inside ``event.get``."""

    JOYBUTTONDOWN = 1
    JOYBUTTONUP = 2
    JOYAXISMOTION = 3
    JOYHATMOTION = 4
    error = RuntimeError

    def __init__(self, count: int = 0, on_get: Callable[[], None] | None = None) -> None:
        self.calls: list[str] = []
        self.opened: list[int] = []
        self._on_get = on_get
        self._shut_down = False
        self.joystick = SimpleNamespace(get_count=lambda: count, Joystick=self._joystick)
        self.event = SimpleNamespace(get=self._get)

    def _joystick(self, index: int) -> SimpleNamespace:
        return SimpleNamespace(init=lambda: self.opened.append(index), get_name=lambda: f"pad {index}")

    def _get(self) -> list[SimpleNamespace]:
        if self._shut_down:
            raise self.error("The event system has been shut down")
        self.calls.append("get")
        if self._on_get is not None:
            self._on_get()
        if self._shut_down:
            raise self.error("The event system has been shut down")
        return [SimpleNamespace(type=self.JOYBUTTONDOWN, joy=0, button=1)]

    def quit(self) -> None:
        self.calls.append("quit")
        self._shut_down = True


def _input_plugin(store: ConfigStore, tmp_path: Path) -> InputPlugin:
    context = PluginContext("input", tmp_path, store, Translator("zh_CN"), ServiceRegistry(), EventBus())
    plugin = InputPlugin(context)
    plugin.on_load()
    return plugin


def test_joystick_polling_opens_controllers_and_reports_buttons(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    plugin = _input_plugin(store, tmp_path)
    pygame = _FakePygame(count=2)
    plugin._pygame = pygame
    observed: list[tuple[InputDevice, tuple[str, ...]]] = []
    plugin._service.subscribe_capture(lambda device, keys: observed.append((device, keys)))

    plugin._poll_joysticks()
    plugin._poll_joysticks()

    assert pygame.opened == [0, 1]
    assert observed[0] == (InputDevice.JOYSTICK, ("button_1",))


def test_shutdown_inside_joystick_polling_defers_pygame_quit(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    plugin = _input_plugin(store, tmp_path)
    # macOS: SDL pumps Cocoa events inside ``event.get``, so app shutdown can run re-entrantly there.
    pygame = _FakePygame(on_get=plugin._stop_listeners)
    plugin._pygame = pygame

    plugin._poll_joysticks()

    assert pygame.calls == ["get", "quit"]
    assert plugin._pygame is None
    assert not plugin._pressed_joystick
    plugin._poll_joysticks()
    assert pygame.calls == ["get", "quit"]


def _recorder(plugin: InputPlugin, binding: HotkeyBinding) -> list[str]:
    triggered: list[str] = []
    plugin._service.register("sample.action", binding, lambda: triggered.append("called"))
    return triggered


def test_keyboard_hotkeys_follow_legacy_press_order_and_suffix_match(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    plugin = _input_plugin(store, tmp_path)
    triggered = _recorder(plugin, HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "m")))
    press = plugin._on_keyboard_press
    release = plugin._on_keyboard_release

    # An unrelated key held before the chord does not prevent the match.
    for key in ("w", "ctrl", "shift", "m"):
        press(SimpleNamespace(name=key) if len(key) > 1 else SimpleNamespace(char=key))
    assert triggered == ["called"]
    # Auto-repeat and releasing part of the chord do not trigger again.
    press(SimpleNamespace(char="m"))
    release(SimpleNamespace(char="m"))
    release(SimpleNamespace(name="shift"))
    assert triggered == ["called"]
    # Order inside the chord is free, but a key pressed in between breaks it.
    for key in ("x", "m"):
        press(SimpleNamespace(char=key))
    press(SimpleNamespace(name="shift"))
    assert triggered == ["called"]
    for key in ("x", "m"):
        release(SimpleNamespace(char=key))
    release(SimpleNamespace(name="shift"))
    press(SimpleNamespace(char="m"))
    press(SimpleNamespace(name="shift"))
    assert triggered == ["called", "called"]


def test_stale_presses_are_released_after_timeout(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    plugin = _input_plugin(store, tmp_path)
    triggered = _recorder(plugin, HotkeyBinding(InputDevice.KEYBOARD, ("d",)))
    plugin._on_keyboard_press(SimpleNamespace(name="ctrl_l"))
    plugin._pressed_keyboard[0].time -= MAX_PRESS_DURATION + 1

    plugin._on_keyboard_press(SimpleNamespace(char="d"))

    assert [item.identifier for item in plugin._pressed_keyboard] == ["d"]
    assert triggered == ["called"]


def test_keyboard_identifiers_and_mouse_filter_match_legacy() -> None:
    assert _pynput_identifier(SimpleNamespace(char="\x01")) == "a"
    assert _pynput_identifier(SimpleNamespace(char="Q")) == "q"
    assert _pynput_identifier(SimpleNamespace(char="é")) is None
    assert _pynput_identifier(SimpleNamespace(name="shift_r")) == "shift"


def test_mouse_ignores_primary_buttons(store: ConfigStore, qapp: QApplication, tmp_path: Path) -> None:
    plugin = _input_plugin(store, tmp_path)
    triggered = _recorder(plugin, HotkeyBinding(InputDevice.MOUSE, ("x1",)))

    plugin._on_mouse_click(0, 0, SimpleNamespace(name="left"), True)
    plugin._on_mouse_click(0, 0, SimpleNamespace(name="right"), True)
    assert not plugin._pressed_mouse
    plugin._on_mouse_click(0, 0, SimpleNamespace(name="x1"), True)
    assert triggered == ["called"]


def test_joysticks_report_triggers_dpad_and_keep_separate_states(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    plugin = _input_plugin(store, tmp_path)
    pygame = _FakePygame()
    triggered = _recorder(plugin, HotkeyBinding(InputDevice.JOYSTICK, ("button_4", "lt")))

    def send(joy: int, kind: int, **fields: object) -> None:
        plugin._handle_joystick_event(pygame, SimpleNamespace(type=kind, joy=joy, **fields))

    # A chord spread over two controllers is not a chord.
    send(0, pygame.JOYBUTTONDOWN, button=4)
    send(1, pygame.JOYAXISMOTION, axis=4, value=1.0)
    assert triggered == []
    send(0, pygame.JOYAXISMOTION, axis=2, value=1.0)
    send(0, pygame.JOYAXISMOTION, axis=4, value=0.8)
    assert triggered == ["called"]
    send(0, pygame.JOYAXISMOTION, axis=4, value=-1.0)
    assert [item.identifier for item in plugin._pressed_joystick[0]] == ["button_4"]

    send(0, pygame.JOYHATMOTION, hat=0, value=(0, 1))
    send(0, pygame.JOYHATMOTION, hat=0, value=(1, 0))
    assert [item.identifier for item in plugin._pressed_joystick[0]] == ["button_4", "dpad_right"]
    send(0, pygame.JOYHATMOTION, hat=0, value=(1, 1))
    assert [item.identifier for item in plugin._pressed_joystick[0]] == ["button_4"]
    send(0, pygame.JOYHATMOTION, hat=0, value=(0, 0))
    assert [item.identifier for item in plugin._pressed_joystick[0]] == ["button_4"]


def test_controller_bindings_use_legacy_button_names() -> None:
    binding = HotkeyBinding(InputDevice.JOYSTICK, ("button_1", "button_12", "dpad_up", "rt"))
    assert _format_binding(binding).split(": ", 1)[1] == "A + Btn12 + Up + RT"


def test_hotkeys_migrate_legacy_bindings_and_capture_devices(store: ConfigStore) -> None:
    config = store.bind(InputConfig, "plugins.input")
    config.bindings.set({"sample.toggle": "shift+ctrl+m"})
    service = _HotkeyService(config)
    triggered: list[str] = []
    observed: list[tuple[InputDevice, tuple[str, ...]]] = []
    default = HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "m"))
    service.register("sample.toggle", default, lambda: triggered.append("called"))

    def observe(device: InputDevice, keys: tuple[str, ...]) -> None:
        observed.append((device, keys))

    service.subscribe_capture(observe)
    assert service.binding("sample.toggle", default) == default
    service.trigger_for_test(InputDevice.KEYBOARD, ("m", "shift", "ctrl"))
    assert triggered == []
    assert observed == [(InputDevice.KEYBOARD, ("ctrl", "shift", "m"))]

    service.unsubscribe_capture(observe)
    service.trigger_for_test(InputDevice.KEYBOARD, ("m", "shift", "ctrl"))
    assert triggered == ["called"]

    controller = HotkeyBinding(InputDevice.JOYSTICK, ("button_1",))
    service.set_binding("sample.toggle", controller)
    service.trigger_for_test(InputDevice.JOYSTICK, ("button_1",))
    assert triggered == ["called", "called"]
    service.set_binding("sample.toggle", HotkeyBinding(None))
    service.trigger_for_test(InputDevice.JOYSTICK, ("button_1",))
    assert triggered == ["called", "called"]


def test_shortcut_dialog_locks_first_device_and_cleans_up_subscription(
    store: ConfigStore, qapp: QApplication
) -> None:
    config = store.bind(InputConfig, "plugins.input")
    service = _HotkeyService(config)
    triggered: list[str] = []
    shortcut = HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "a"))
    service.register("sample.record", shortcut, lambda: triggered.append("called"))
    dialog = _HotkeySettingDialog(service, shortcut)

    service.trigger_for_test(InputDevice.KEYBOARD, ("ctrl",))
    service.trigger_for_test(InputDevice.KEYBOARD, ("ctrl", "shift"))
    service.trigger_for_test(InputDevice.KEYBOARD, ("ctrl", "shift", "a"))
    service.trigger_for_test(InputDevice.KEYBOARD, ("ctrl", "shift"))
    service.trigger_for_test(InputDevice.KEYBOARD, ("ctrl",))
    service.trigger_for_test(InputDevice.KEYBOARD, ())
    assert dialog.binding == shortcut
    assert triggered == []

    dialog._clear()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.binding == HotkeyBinding(None)
    assert not service._capture_listeners


def test_region_values_accept_global_pixel_rectangles(store: ConfigStore) -> None:
    config = store.bind(RegionConfig, "plugins.region")
    rect = QRect(100, 200, 300, 40)
    config.regions.set({"hp_bar": [rect.x(), rect.y(), rect.width(), rect.height()]})

    assert config.regions.value["hp_bar"] == [100, 200, 300, 40]


def test_input_partial_initialization_is_cleaned_and_service_recovers(store, tmp_path, monkeypatch):
    import pytest

    plugin = _input_plugin(store, tmp_path)
    stopped = []

    def fail():
        plugin._keyboard_listener = SimpleNamespace(stop=lambda: stopped.append("keyboard"))
        plugin._mouse_listener = SimpleNamespace(stop=lambda: stopped.append("mouse"))
        plugin._pygame = _FakePygame()
        raise RuntimeError("pygame initialization failed")

    monkeypatch.setattr(plugin, "_start_keyboard_listener", fail)
    plugin.config.enable_global_listener.set(True)
    with pytest.raises(RuntimeError):
        plugin.on_activate()
    pygame = plugin._pygame
    plugin.ctx.release()
    assert stopped == ["keyboard", "mouse"]
    assert pygame.calls == ["quit"]
    assert plugin._keyboard_listener is plugin._mouse_listener is plugin._pygame is None
    assert plugin.ctx.services.get(HotkeyApi) is None
    plugin.config.enable_global_listener.set(False)
    plugin.on_activate()
    assert plugin.ctx.services.get(HotkeyApi) is plugin._service
    plugin.ctx.release()


def test_region_bounds_validate_storage_import_and_runtime(store):
    import pytest

    config = store.bind(RegionConfig, "plugins.region")
    for rect in ([0, 0, 2**40, 20], [0, 0, 0, 20], [0, 0, 20, -1], [2**31 - 2, 0, 5, 1]):
        with pytest.raises(ValueError):
            config.regions.set({"test": rect})
        with pytest.raises(ValueError):
            store.replace_for_restart({"plugins": {"region": {"regions": {"test": rect}}}})
        loaded = RegionConfig("plugins.region", {"regions": {"test": rect}}, lambda *_: None)
        assert loaded.regions.value == {}
    config.regions.set({"secondary": [-1920, -1080, 100, 20]})
    assert config.regions.value["secondary"] == [-1920, -1080, 100, 20]


def test_real_input_initialization_cleans_keyboard_when_mouse_start_fails(store, tmp_path, monkeypatch):
    import sys

    import pytest

    calls = []

    class Keyboard:
        def __init__(self, **kwargs):
            pass

        def start(self):
            calls.append("keyboard started")

        def stop(self):
            calls.append("keyboard stopped")

    class Mouse(Keyboard):
        def start(self):
            raise RuntimeError("mouse unavailable")

        def stop(self):
            calls.append("mouse stopped")

    monkeypatch.setitem(
        sys.modules,
        "pynput",
        SimpleNamespace(keyboard=SimpleNamespace(Listener=Keyboard), mouse=SimpleNamespace(Listener=Mouse)),
    )
    plugin = _input_plugin(store, tmp_path)
    plugin.config.enable_global_listener.set(True)
    with pytest.raises(RuntimeError, match="mouse unavailable"):
        plugin.on_activate()
    plugin.ctx.release()
    assert calls == ["keyboard started", "keyboard stopped", "mouse stopped"]
