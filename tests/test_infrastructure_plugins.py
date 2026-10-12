"""Unit coverage for P2 infrastructure contracts that does not need input hardware."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.capture.api import make_frame
from nightreign_overlay.plugins.capture.plugin import CapturePlugin
from nightreign_overlay.plugins.input.config import InputConfig
from nightreign_overlay.plugins.input.plugin import _HotkeyService
from nightreign_overlay.plugins.region.config import RegionConfig


def test_capture_frame_is_detached() -> None:
    source = QImage(4, 3, QImage.Format.Format_ARGB32)
    source.fill(0xFF112233)
    frame = make_frame(source)

    source.fill(0xFF000000)
    assert frame.image.pixelColor(0, 0).name() == "#112233"


def test_capture_stream_runs_only_while_leased(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    context = PluginContext(
        "capture",
        tmp_path,
        store,
        Translator("zh_CN"),
        ServiceRegistry(),
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


def test_hotkeys_persist_canonical_combo_and_support_injection(store: ConfigStore) -> None:
    config = store.bind(InputConfig, "plugins.input")
    service = _HotkeyService(config)
    triggered: list[str] = []
    service.register("sample.toggle", "shift+ctrl+m", lambda: triggered.append("called"))

    assert config.bindings.value == {"sample.toggle": "ctrl+m+shift"}
    service.trigger_for_test("m+ctrl+shift")
    assert triggered == ["called"]


def test_region_values_accept_global_pixel_rectangles(store: ConfigStore) -> None:
    config = store.bind(RegionConfig, "plugins.region")
    rect = QRect(100, 200, 300, 40)
    config.regions.set({"hp_bar": [rect.x(), rect.y(), rect.width(), rect.height()]})

    assert config.regions.value["hp_bar"] == [100, 200, 300, 40]
