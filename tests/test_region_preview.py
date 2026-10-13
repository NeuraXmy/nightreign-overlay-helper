"""The "show current region" hover icon and the shared region preview window."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QEnterEvent
from PyQt6.QtWidgets import QApplication, QWidget

from feature_fakes import FeatureServices
from nightreign_overlay.core import i18n
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.paths import resource_path
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin import Plugin
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.art_timer import plugin as art_plugin
from nightreign_overlay.plugins.art_timer.plugin import ArtTimerPlugin
from nightreign_overlay.plugins.day_timer import plugin as day_plugin
from nightreign_overlay.plugins.day_timer.plugin import DayTimerPlugin
from nightreign_overlay.plugins.rain_timer import plugin as rain_plugin
from nightreign_overlay.plugins.rain_timer.plugin import RainTimerPlugin
from nightreign_overlay.plugins.region import plugin as region_plugin
from nightreign_overlay.plugins.region.api import RegionApi, RegionStatus
from nightreign_overlay.plugins.region.plugin import RegionPlugin
from nightreign_overlay.ui.components import HotkeySettingCard


def _region(store: ConfigStore, tmp_path: Path) -> tuple[RegionPlugin, RegionApi]:
    services = ServiceRegistry()
    plugin = RegionPlugin(PluginContext("region", tmp_path, store, Translator("zh_CN"), services, EventBus()))
    plugin.on_load()
    plugin.on_activate()
    return plugin, services.require(RegionApi)


def _enter(widget: QWidget) -> None:
    QApplication.sendEvent(widget, QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))


def test_preview_outlines_the_calibrated_region_in_one_reused_window(
    store: ConfigStore, qapp: QApplication, tmp_path: Path
) -> None:
    plugin, regions = _region(store, tmp_path)
    assert regions.show_preview("missing") is False
    assert plugin._preview is None

    regions.save_region_for_test("a", QRect(10, 20, 30, 40))
    regions.save_region_for_test("b", QRect(50, 60, 70, 80))
    assert regions.show_preview("a") is True
    preview = plugin._preview
    assert preview is not None and preview.isVisible()
    assert preview.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert preview.region_geometry() == QRect(10, 20, 30, 40)
    assert preview.color == QColor(region_plugin._RECT_COLOR)

    assert regions.show_preview("b", "#3235eb") is True
    assert plugin._preview is preview
    assert preview.region_geometry() == QRect(50, 60, 70, 80)
    assert preview.color == QColor("#3235eb")

    regions.hide_preview()
    assert not preview.isVisible()
    regions.show_preview("a")
    assert regions.show_preview("missing") is False
    assert not preview.isVisible()

    plugin.ctx.release()
    assert plugin._preview is None


class _Screen:
    def __init__(self, geometry: QRect, ratio: float) -> None:
        self._geometry = geometry
        self._ratio = ratio

    def geometry(self) -> QRect:
        return self._geometry

    def devicePixelRatio(self) -> float:
        return self._ratio


def test_preview_inverts_the_selector_pixel_convention(monkeypatch: pytest.MonkeyPatch) -> None:
    # The selector stores ``local * dpr + screen offset``; Qt on Windows reports native screen origins.
    primary = _Screen(QRect(0, 0, 1440, 900), 2.0)
    secondary = _Screen(QRect(2880, 0, 1920, 1080), 1.0)

    class _App:
        @staticmethod
        def screens() -> list[_Screen]:
            return [primary, secondary]

        @staticmethod
        def primaryScreen() -> _Screen:
            return primary

    monkeypatch.setattr(region_plugin, "QGuiApplication", _App)
    assert region_plugin._pixels_to_logical(QRect(200, 100, 400, 200)) == QRect(100, 50, 200, 100)
    assert region_plugin._pixels_to_logical(QRect(2890, 20, 30, 40)) == QRect(2890, 20, 30, 40)
    # Off every screen: fall back to the primary screen's scale.
    assert region_plugin._pixels_to_logical(QRect(-400, -200, 40, 20)) == QRect(-200, -100, 20, 10)


def test_status_previews_on_hover_and_describes_the_region(
    store: ConfigStore, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    translator = Translator("zh_CN")
    translator.load_dir(i18n.CORE_NAMESPACE, resource_path("i18n"))
    monkeypatch.setattr(i18n, "_translator", translator)
    services = ServiceRegistry()
    status = RegionStatus(services, "day_timer.detect_region", "#3235eb")
    assert status.label.text() == "未标定"
    assert not status.calibrated
    assert status.toolTip() == "尚未标定区域"
    _enter(status)  # The region service is not active yet: nothing to show, nothing breaks.

    fakes = FeatureServices(store, tmp_path)
    status = RegionStatus(fakes.services, "day_timer.detect_region", "#3235eb")
    host = QWidget()
    status.setParent(host)
    host.show()
    fakes.region.save_region_for_test("day_timer.detect_region", QRect(1, 2, 30, 40))
    _enter(status)
    assert status.calibrated
    assert status.label.text() == "已标定"
    assert status.toolTip() == "显示当前区域：(1, 2)，30 × 40 像素"
    assert fakes.region.previews == [("day_timer.detect_region", "#3235eb")]

    fakes.region.previews.clear()
    status.leaveEvent(None)
    assert fakes.region.previews == [None]
    # Switching pages hides the icon without a leave event.
    fakes.region.previews.clear()
    host.hide()
    assert fakes.region.previews == [None]


@pytest.mark.parametrize(
    ("plugin_cls", "module", "region", "color"),
    [
        (DayTimerPlugin, day_plugin, "day_timer.detect_region", None),
        (RainTimerPlugin, rain_plugin, "rain_timer.hp_region", "#a84747"),
        (ArtTimerPlugin, art_plugin, "art_timer.art_region", "#3235eb"),
    ],
)
def test_calibrate_region_card_carries_the_region_status(
    store: ConfigStore,
    qapp: QApplication,
    tmp_path: Path,
    plugin_cls: type[Plugin],
    module: object,
    region: str,
    color: str | None,
) -> None:
    fakes = FeatureServices(store, tmp_path)
    plugin = plugin_cls(fakes.context(plugin_cls.manifest.id, Path(module.__file__).parent))
    plugin.on_load()
    host = QWidget()
    panel = plugin.create_settings_widget(host)
    (status,) = panel.findChildren(RegionStatus)
    card = status.parent()
    assert isinstance(card, HotkeySettingCard)
    assert card._action_id == f"{plugin_cls.manifest.id}.calibrate_region"
    uncalibrated = status.label.text()
    fakes.region.save_region_for_test(region, QRect(1, 2, 3, 4))
    card.refresh()  # Also run after the card's "calibrate" action and by the page-level reset.
    assert status.label.text() != uncalibrated
    _enter(status)
    assert fakes.region.previews == [(region, color)]
