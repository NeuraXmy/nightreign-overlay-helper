"""Coverage for day_timer plugin behaviour that does not need a real game window."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.game_window import GameWindowMonitor
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.platforms import PlatformBackend
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.day_timer import plugin as day_timer_plugin
from nightreign_overlay.plugins.day_timer.api import Phase
from nightreign_overlay.plugins.day_timer.detector import DayDetector
from nightreign_overlay.plugins.day_timer.plugin import DayTimerPlugin
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding, InputDevice
from nightreign_overlay.plugins.input.plugin import InputPlugin
from nightreign_overlay.plugins.region import plugin as region_plugin
from nightreign_overlay.plugins.region.api import RegionApi, RegionTarget
from nightreign_overlay.plugins.region.plugin import RegionPlugin
from nightreign_overlay.ui.components import MultiButtonSettingCard
from nightreign_overlay.ui.overlay import OverlayManager

_TEMPLATES = Path(__file__).parents[1] / "src/nightreign_overlay/plugins/day_timer/templates"


class _FakeBackend(PlatformBackend):
    name = "fake"
    supports_foreground_detection = True
    supports_transparent_overlay = True

    def foreground_window_title(self) -> str | None:
        return None


def _day_timer_context(
    store: ConfigStore, tmp_path: Path, services: ServiceRegistry, events: EventBus
) -> PluginContext:
    return PluginContext("day_timer", tmp_path, store, Translator("zh_CN"), services, events)


def _input_context(
    store: ConfigStore, tmp_path: Path, services: ServiceRegistry, events: EventBus
) -> PluginContext:
    return PluginContext("input", tmp_path, store, Translator("zh_CN"), services, events)


def test_calibrate_region_hotkey_is_registered_with_empty_default(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    services = ServiceRegistry()
    events = EventBus()
    input_plugin = InputPlugin(_input_context(store, tmp_path, services, events))
    input_plugin.on_load()

    plugin = DayTimerPlugin(_day_timer_context(store, tmp_path, services, events))
    plugin.on_load()
    plugin._register_hotkeys(services.require(HotkeyApi))

    hotkeys = services.require(HotkeyApi)
    assert hotkeys.binding("day_timer.calibrate_region", HotkeyBinding(None)) == HotkeyBinding(None)
    hotkeys.set_binding(
        "day_timer.calibrate_region", HotkeyBinding(InputDevice.KEYBOARD, ("ctrl", "shift", "c"))
    )
    assert hotkeys.binding("day_timer.calibrate_region", HotkeyBinding(None)) == HotkeyBinding(
        InputDevice.KEYBOARD, ("ctrl", "shift", "c")
    )


def test_detector_handles_padded_rows_and_out_of_frame_regions(qapp: QApplication) -> None:
    detector = DayDetector(_TEMPLATES)
    assert all(detector.available(language) for language in ("chs", "cht", "eng", "jp"))
    frame = QImage(400, 300, QImage.Format.Format_RGB32)
    frame.fill(0)

    # 134 px * 3 bytes = 402, padded to 404 per row by Qt; this used to fail to reshape.
    assert detector.detect(frame, QRect(10, 10, 134, 40), "chs", 0.5).day is None
    assert detector.detect(frame, QRect(350, 280, 134, 40), "chs", 0.5).day is None
    assert detector.detect(frame, QRect(500, 500, 20, 20), "chs", 0.5).day is None


@pytest.mark.parametrize("language", ["chs", "eng"])
@pytest.mark.parametrize("day", [1, 2, 3])
def test_detector_widens_day_ii_and_iii_regions_around_the_day_i_box(
    qapp: QApplication, language: str, day: int
) -> None:
    """Only the DAY I box is calibrated; wider DAY II/III labels must still be matched (legacy ratios)."""
    label = QImage(str(_TEMPLATES / f"{language}_{day}.png")).scaledToHeight(40)
    frame = QImage(800, 200, QImage.Format.Format_RGB32)
    frame.fill(0)
    painter = QPainter(frame)
    painter.drawImage(100, 50, label)
    painter.end()
    day1 = QImage(str(_TEMPLATES / f"{language}_1.png"))
    width = round(day1.width() * 40 / day1.height())
    region = QRect(100 + label.width() // 2 - width // 2, 50, width, 40)

    result = DayDetector(_TEMPLATES).detect(frame, region, language, 0.8)
    assert result.day == day
    assert result.scores[day - 1] < 0.8


def _timer_plugin(
    store: ConfigStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[DayTimerPlugin, list[float]]:
    services = ServiceRegistry()
    events = EventBus()
    InputPlugin(_input_context(store, tmp_path, services, events)).on_load()
    plugin = DayTimerPlugin(_day_timer_context(store, tmp_path, services, events))
    plugin.ctx._translator.load_dir("day_timer", Path(day_timer_plugin.__file__).parent / "i18n")
    plugin.on_load()
    clock = [1000.0]
    monkeypatch.setattr(day_timer_plugin.time, "monotonic", lambda: clock[0])
    return plugin, clock


def test_next_day_cycles_like_legacy_and_logs_the_source(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    plugin, _ = _timer_plugin(store, tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO):
        plugin._start_next_day()
        assert (plugin.day, plugin.phase) == (1, Phase.FIRST_CIRCLE_STABLE)
        plugin._start_next_day("button")
        assert plugin.day == 2
        plugin._start_next_day()
        assert plugin.day == 1
        plugin._start_day(3)
        plugin._start_next_day()
        assert (plugin.day, plugin.phase) == (1, Phase.FIRST_CIRCLE_STABLE)
    assert "Day 1 started by shortcut." in caplog.messages
    assert "Day 2 started by button." in caplog.messages


def test_forward_and_backward_walk_phases_like_legacy(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    plugin, clock = _timer_plugin(store, tmp_path, monkeypatch)
    plugin._forward()  # Nothing to shift before a day has started.
    assert plugin._phase_started is None

    plugin._start_day(1)
    clock[0] += 265
    with caplog.at_level(logging.INFO):
        plugin._forward("button")
    assert plugin.phase == Phase.FIRST_CIRCLE_SHRINK
    assert "Phase progress to FIRST_CIRCLE_SHRINK." in caplog.messages
    assert "Day timer forwarded 10s by button." in caplog.messages

    # Rewinding past the start of the shrink phase steps back into the stable phase.
    with caplog.at_level(logging.INFO):
        plugin._backward()
    assert plugin.phase == Phase.FIRST_CIRCLE_STABLE
    assert clock[0] - plugin._phase_started == pytest.approx(265)
    assert "Phase back to FIRST_CIRCLE_STABLE." in caplog.messages

    # The first phase cannot start in the future; it clamps to now.
    clock[0] -= 260
    plugin._backward()
    assert plugin.phase == Phase.FIRST_CIRCLE_STABLE
    assert plugin._phase_started == clock[0]


def test_hud_text_matches_legacy_wording(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, clock = _timer_plugin(store, tmp_path, monkeypatch)
    plugin._label = label = day_timer_plugin.QLabel()
    plugin._start_day(1)
    assert label.text() == "DAY I - 4:30 后第一圈开始缩圈"
    clock[0] += 270 + 180 + 1
    plugin._update_timer()
    assert label.text() == "DAY I - 3:29 后第二圈开始缩圈"
    clock[0] += 209 + 1
    plugin._update_timer()
    assert label.text() == "DAY I - 2:59 后第二圈缩圈结束"
    clock[0] += 180
    plugin._update_timer()
    assert label.text() == "DAY I - 夜晚BOSS战 0:01"
    plugin._start_day(3)
    clock[0] += 65
    plugin._update_timer()
    assert label.text() == "DAY III - 1:05"


def test_detection_refreshes_banner_start_and_restarts_a_new_expedition(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    plugin, clock = _timer_plugin(store, tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO):
        plugin._detected_day(1)
        clock[0] += 1
        plugin._detected_day(1)  # Banner still visible: the countdown restarts silently.
    assert plugin._phase_started == clock[0]
    assert caplog.messages.count("Day 1 started.") == 1

    # A later DAY I (a new expedition on the same day number) starts over like the legacy app.
    clock[0] += 600
    plugin._update_timer()
    assert plugin.phase == Phase.SECOND_CIRCLE_STABLE
    with caplog.at_level(logging.INFO):
        plugin._detected_day(1)
    assert plugin.phase == Phase.FIRST_CIRCLE_STABLE
    assert caplog.messages.count("Day 1 started.") == 2


def test_settings_page_offers_manual_adjust_buttons(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, clock = _timer_plugin(store, tmp_path, monkeypatch)
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    cards = [card for card in panel.findChildren(MultiButtonSettingCard)]
    assert len(cards) == 1
    buttons = {button.text(): button for button in cards[0].findChildren(QPushButton)}
    assert list(buttons) == ["开始下一天", "快退", "快进"]

    buttons["开始下一天"].click()
    assert plugin.day == 1
    buttons["快进"].click()
    assert clock[0] - plugin._phase_started == 10
    buttons["快退"].click()
    assert clock[0] - plugin._phase_started == 0


def test_region_request_hides_and_restores_main_window(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = ServiceRegistry()
    events = EventBus()
    backend = _FakeBackend()
    services.register(PlatformBackend, backend)
    app_config = store.bind(AppConfig, "app")
    monitor = GameWindowMonitor(backend, events)
    overlays = OverlayManager(backend, app_config, monitor)
    services.register(OverlayManager, overlays)

    region = RegionPlugin(PluginContext("region", tmp_path, store, Translator("zh_CN"), services, events))
    region.on_load()
    region.on_activate()

    calls: list[str] = []
    overlays.mainWindowHideRequested.connect(lambda: calls.append("hide"))
    overlays.mainWindowShowRequested.connect(lambda: calls.append("show"))
    monkeypatch.setattr(region_plugin, "_HIDE_SETTLE_MS", 0)

    def fake_run(dialog: region_plugin._SelectionDialog) -> dict[int, QRect]:
        # The selector must only appear after the main window has been asked to hide.
        calls.append("select")
        assert dialog.annotateButton.text() == "点我并框出 DAY I 图标 的区域"
        return {0: QRect(10, 20, 30, 40)}

    monkeypatch.setattr(region_plugin._SelectionDialog, "run", fake_run)

    plugin = DayTimerPlugin(_day_timer_context(store, tmp_path, services, events))
    plugin.ctx._translator.load_dir("day_timer", Path(day_timer_plugin.__file__).parent / "i18n")
    plugin.on_load()
    plugin._calibrate_region()

    assert calls == ["hide", "select", "show"]
    assert services.require(RegionApi).region("day_timer.detect_region") == QRect(10, 20, 30, 40)

    overlays.deleteLater()
    monitor.stop()


def _mouse(dialog: QWidget, kind: QEvent.Type, x: int, y: int) -> None:
    pressed = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, pressed, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(dialog, event)


def _drag(dialog: QWidget, start: tuple[int, int], end: tuple[int, int]) -> None:
    _mouse(dialog, QEvent.Type.MouseButtonPress, *start)
    _mouse(dialog, QEvent.Type.MouseMove, *end)
    _mouse(dialog, QEvent.Type.MouseButtonRelease, *end)


def _selection_dialog() -> region_plugin._SelectionDialog:
    texts = region_plugin._SelectionTexts("annotate", "hint", "cancel", "save")
    return region_plugin._SelectionDialog(texts, False, logging.getLogger("test.region"))


def test_selection_dialog_follows_legacy_draw_adjust_and_save_flow(
    qapp: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    dialog = _selection_dialog()
    ratio = dialog._device_pixel_ratio
    origin = dialog._screen_geometry.topLeft()

    # Dragging before clicking the annotation button draws nothing, and the box does not close the dialog.
    _drag(dialog, (10, 10), (100, 100))
    assert dialog.items == []
    dialog.annotateButton.click()
    _drag(dialog, (10, 10), (100, 60))
    assert len(dialog.items) == 1
    assert dialog.result() != QDialog.DialogCode.Accepted

    # The bottom-right handle resizes, the interior moves.
    rect = dialog.items[0].rect
    _drag(dialog, (rect.right(), rect.bottom()), (rect.right() + 20, rect.bottom() + 10))
    assert dialog.items[0].rect == QRect(10, 10, 111, 61)
    _drag(dialog, (40, 30), (45, 35))
    assert dialog.items[0].rect == QRect(15, 15, 111, 61)

    with caplog.at_level(logging.INFO, "test.region"):
        dialog.saveButton.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    expected = region_plugin._scale_rect(QRect(15, 15, 111, 61), ratio).translated(origin)
    assert dialog.selected == expected
    assert any("Saved rect" in message for message in caplog.messages)


def test_selection_dialog_cancel_and_empty_save(qapp: QApplication) -> None:
    dialog = _selection_dialog()
    dialog.saveButton.click()
    # Saving without a box keeps the selector open.
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.cancelButton.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.selected is None


def test_selection_dialog_keeps_the_last_box_per_annotation_and_samples_frozen_pixels(
    qapp: QApplication,
) -> None:
    texts = region_plugin._SelectionTexts("annotate", "hint", "cancel", "save")
    annotations = [("normal", "#b83232"), ("rain", "#c03184")]
    dialog = region_plugin._SelectionDialog(texts, False, logging.getLogger("test.region"), annotations)
    ratio = dialog._device_pixel_ratio
    pixmap = QPixmap(dialog._screen_geometry.size() * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor(10, 200, 30))
    dialog._pixmap = pixmap
    assert [button.text() for button in dialog.annotateButtons] == ["normal", "rain"]

    dialog.annotateButtons[1].click()
    _drag(dialog, (10, 10), (40, 30))
    dialog.annotateButtons[0].click()
    _drag(dialog, (100, 100), (130, 120))
    dialog.annotateButtons[0].click()
    _drag(dialog, (200, 100), (260, 140))
    dialog.saveButton.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    origin = dialog._screen_geometry.topLeft()
    assert dialog.selections == {
        0: region_plugin._scale_rect(QRect(200, 100, 61, 41), ratio).translated(origin),
        1: region_plugin._scale_rect(QRect(10, 10, 31, 21), ratio).translated(origin),
    }
    sample = dialog.sample(1)
    assert sample is not None and sample.pixelColor(0, 0) == QColor(10, 200, 30)
    assert dialog.sample(2) is None


def test_request_samples_needs_a_frozen_screen(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _NoPermissionBackend(_FakeBackend):
        requested = 0

        def has_screen_capture_access(self) -> bool:
            return False

        def request_screen_capture_access(self) -> None:
            self.requested += 1

    services = ServiceRegistry()
    backend = _NoPermissionBackend()
    services.register(PlatformBackend, backend)
    region = RegionPlugin(PluginContext("region", tmp_path, store, Translator("zh_CN"), services, EventBus()))
    region.on_load()
    region.on_activate()
    monkeypatch.setattr(region_plugin, "_HIDE_SETTLE_MS", 0)
    opened: list[object] = []
    monkeypatch.setattr(region_plugin._SelectionDialog, "run", lambda dialog: opened.append(dialog) or {})

    api = services.require(RegionApi)
    assert api.request_samples([RegionTarget("a", "A")]) is None
    assert backend.requested == 1 and opened == []

    # Region selection still works over the live screen without the permission.
    assert api.request_region("key", "A") is None
    assert len(opened) == 1


def test_request_samples_returns_the_frozen_pixels_of_boxed_targets(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = ServiceRegistry()
    region = RegionPlugin(PluginContext("region", tmp_path, store, Translator("zh_CN"), services, EventBus()))
    region.on_load()
    region.on_activate()
    monkeypatch.setattr(region_plugin, "_HIDE_SETTLE_MS", 0)
    sample = QImage(2, 2, QImage.Format.Format_RGB32)
    labels: list[list[str]] = []

    def fake_run(dialog: region_plugin._SelectionDialog) -> dict[int, QRect]:
        labels.append([button.text() for button in dialog.annotateButtons])
        return {1: QRect(1, 2, 3, 4)}

    monkeypatch.setattr(region_plugin._SelectionDialog, "run", fake_run)
    monkeypatch.setattr(region_plugin._SelectionDialog, "sample", lambda _dialog, index: sample)

    samples = services.require(RegionApi).request_samples(
        [RegionTarget("normal", "N", "#b83232"), RegionTarget("rain", "R")]
    )
    assert labels == [["N", "R"]]
    assert samples == {"rain": sample}
    # Sampling never persists a region.
    assert region.config.regions.value == {}
