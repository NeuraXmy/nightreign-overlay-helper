"""In-memory stand-ins for the capture / region / HUD services used by feature plugin tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.capture.api import CaptureApi, FrameCaptured
from nightreign_overlay.plugins.hud.api import HudApi
from nightreign_overlay.plugins.input.plugin import InputPlugin
from nightreign_overlay.plugins.region.api import RegionApi, RegionTarget


class FakeCapture(CaptureApi):
    def __init__(self) -> None:
        self.hdr = False
        self.frame: FrameCaptured | None = None
        self.captures = 0
        self.streams: set[str] = set()

    def latest_frame(self) -> FrameCaptured | None:
        return self.frame

    def capture_now(self) -> FrameCaptured | None:
        self.captures += 1
        return self.frame

    def acquire_stream(self, owner: str) -> None:
        self.streams.add(owner)

    def release_stream(self, owner: str) -> None:
        self.streams.discard(owner)

    def hdr_enabled(self) -> bool:
        return self.hdr


class FakeRegion(RegionApi):
    def __init__(self) -> None:
        self.regions: dict[str, QRect] = {}
        self.requests: list[tuple[str, str | None, str | None]] = []
        self.sample_requests: list[list[RegionTarget]] = []
        self.samples: dict[str, QImage] | None = None
        self.previews: list[tuple[str, str | None] | None] = []

    def request_region(self, key: str, label: str | None = None, color: str | None = None) -> QRect | None:
        self.requests.append((key, label, color))
        return self.regions.get(key)

    def request_samples(self, targets: Sequence[RegionTarget]) -> dict[str, QImage] | None:
        self.sample_requests.append(list(targets))
        return self.samples

    def region(self, key: str) -> QRect | None:
        return self.regions.get(key)

    def clear_region(self, key: str) -> None:
        self.regions.pop(key, None)

    def show_preview(self, key: str, color: str | None = None) -> bool:
        self.previews.append((key, color))
        return key in self.regions

    def hide_preview(self) -> None:
        self.previews.append(None)

    def save_region_for_test(self, key: str, rect: QRect) -> None:
        self.regions[key] = rect


class FakeHud(HudApi):
    def __init__(self) -> None:
        self.widgets: dict[str, tuple[str, QWidget, int]] = {}

    def add_widget(self, owner: str, widget: QWidget, order: int = 100) -> str:
        token = f"{owner}:{len(self.widgets)}"
        self.widgets[token] = (owner, widget, order)
        widget.show()
        return token

    def remove_widget(self, token: str) -> None:
        self.widgets.pop(token, None)

    def remove_owner(self, owner: str) -> None:
        for token in [token for token, entry in self.widgets.items() if entry[0] == owner]:
            self.remove_widget(token)


class FeatureServices:
    """Input (real), capture, region and HUD services for one feature plugin under test."""

    def __init__(self, store: ConfigStore, tmp_path: Path) -> None:
        self.store = store
        self.services = ServiceRegistry()
        self.events = EventBus()
        self.capture = FakeCapture()
        self.region = FakeRegion()
        self.hud = FakeHud()
        for api, impl in ((CaptureApi, self.capture), (RegionApi, self.region), (HudApi, self.hud)):
            self.services.register(api, impl)
        self.input = InputPlugin(self.context("input", tmp_path))
        self.input.on_load()

    def context(self, plugin_id: str, root_dir: Path) -> PluginContext:
        translator = Translator("zh_CN")
        if (root_dir / "i18n").is_dir():
            translator.load_dir(plugin_id, root_dir / "i18n")
        return PluginContext(plugin_id, root_dir, self.store, translator, self.services, self.events)


def solid_image(width: int, height: int, rgb: tuple[int, int, int]) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(*rgb))
    return image
