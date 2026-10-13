"""Character art (ultimate) countdown: detect the art icon shortly after the art key is pressed."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest
from nightreign_overlay.plugins.art_timer.config import ArtTimerConfig
from nightreign_overlay.plugins.art_timer.detector import ArtDetector
from nightreign_overlay.plugins.capture.api import CaptureApi
from nightreign_overlay.plugins.hud.api import HudApi, HudTimerBar
from nightreign_overlay.plugins.input.api import HotkeyApi, HotkeyBinding
from nightreign_overlay.plugins.region.api import RegionApi
from nightreign_overlay.ui.components import ConfigRangeCard, HotkeySettingCard, SettingSection, SettingsPanel

_REGION_KEY = "art_timer.art_region"
_USE_ART = "art_timer.use_art"
_CALIBRATE_REGION = "art_timer.calibrate_region"
# Legacy colour of the selector annotation.
_REGION_COLOR = "#3235eb"


@dataclass(frozen=True)
class _ArtInfo:
    """Legacy ``art_info``: the effect starts ``delay`` seconds after detection and lasts ``duration``."""

    delay: float
    duration: float
    color: str


_ART_INFO = {
    "duchess": _ArtInfo(2, 13, "#cccccc"),
    "recluse": _ArtInfo(2, 13, "#d11010"),
    "revenant": _ArtInfo(2, 13, "#9bdfdf"),
    "scholar": _ArtInfo(2, 20, "#cecece"),
    "executor": _ArtInfo(2, 15, "#c98941"),
}


def _format_period(seconds: int) -> str:
    return f"{max(seconds, 0) // 60}:{max(seconds, 0) % 60:02d}"


class ArtTimerPlugin(Plugin):
    manifest = PluginManifest(
        id="art_timer",
        kind=PluginKind.FEATURE,
        icon="CALORIES",
        requires=("capture", "hud", "input", "region"),
        order=20,
    )

    def on_load(self) -> None:
        self.config = self.ctx.config(ArtTimerConfig)
        self._art_type: str | None = None
        self._art_started: float | None = None
        self._detector: ArtDetector | None = None
        self._hud: HudTimerBar | None = None
        self._calibrating = False
        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._update_timer)
        # Pressing the art key again before the detection restarts the delay, like the legacy app.
        self._detect_timer = QTimer(self)
        self._detect_timer.setSingleShot(True)
        self._detect_timer.timeout.connect(self._detect_art)

    def on_activate(self) -> None:
        self._detector = ArtDetector(self.ctx.resource("icons"))
        if missing := self._detector.missing():
            self.ctx.log.error("Art icons are unavailable: %s", ", ".join(missing))
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        self.ctx.log.info("Art region: %s", list(region.getRect()) if region else None)
        self._register_hotkeys(self.ctx.services.require(HotkeyApi))
        self._create_hud(self.ctx.services.require(HudApi))
        self._clock.start()
        self.ctx.on_cleanup(self._clock.stop)
        self.ctx.on_cleanup(self._detect_timer.stop)

    def on_deactivate(self) -> None:
        self._hud = None
        self._detector = None

    def _register_hotkeys(self, hotkeys: HotkeyApi) -> None:
        # The legacy app shipped both shortcuts unbound.
        for action, callback in ((_USE_ART, self._use_art), (_CALIBRATE_REGION, self._calibrate_region)):
            hotkeys.register(action, HotkeyBinding(None), callback)
            self.ctx.on_cleanup(lambda action=action: hotkeys.unregister(action))

    def _create_hud(self, hud: HudApi) -> None:
        widget = HudTimerBar(_ART_INFO["duchess"].color)
        self._hud = widget
        token = hud.add_widget(self.id, widget, order=20)
        self.ctx.on_cleanup(lambda: hud.remove_widget(token))
        # The HUD shows every new widget; an idle countdown hides itself again.
        self._update_timer()

    # -- detection ----------------------------------------------------------------------------

    def _use_art(self) -> None:
        delay = self.config.detect_delay_ms.value
        self.ctx.log.info("Will detect art in %s seconds.", delay / 1000)
        self._detect_timer.start(delay)

    def _detect_art(self) -> None:
        """Capture one frame after the delay; there is no continuous stream for this feature."""
        if self._calibrating or self._detector is None:
            return
        region = self.ctx.services.require(RegionApi).region(_REGION_KEY)
        frame = self.ctx.services.require(CaptureApi).capture_now() if region is not None else None
        result = (
            self._detector.detect(
                frame.image, region, self.config.match_threshold.value / 1000, hdr=frame.hdr
            )
            if frame is not None and region is not None
            else None
        )
        if result is not None:
            for art_type, score in result.scores.items():
                self.ctx.log.info("Art type: %s, score: %.4f", art_type, score)
            if result.art_type is not None:
                self.ctx.log.info("Detected art type: %s, score: %.4f", result.art_type, result.best_score)
            else:
                self.ctx.log.info("No art detected, best score: %.4f", result.best_score)
        if result is None or result.art_type is None:
            self.ctx.log.info("No art detected.")
            return
        self.ctx.log.info("detected art: %s", result.art_type)
        self._art_type = result.art_type
        self._art_started = time.monotonic()
        self._update_timer()

    # -- countdown ----------------------------------------------------------------------------

    def _update_timer(self) -> None:
        if self._hud is None:
            return
        if self._art_type is None or self._art_started is None:
            self._hud.set_progress(0.0, "")
            return
        info = _ART_INFO[self._art_type]
        elapsed = max(0.0, time.monotonic() - self._art_started - info.delay)
        if elapsed > info.duration:
            self._art_type = self._art_started = None
            self._hud.set_progress(0.0, "")
            return
        text = self.ctx.tr(
            "hud.text",
            name=self.ctx.tr(f"hud.{self._art_type}"),
            remaining=_format_period(int(max(info.duration - elapsed, 0))),
        )
        self._hud.set_progress(1.0 - elapsed / info.duration, text, info.color)

    # -- calibration --------------------------------------------------------------------------

    def _calibrate_region(self) -> None:
        if self._calibrating:
            return
        self._calibrating = True
        try:
            self.ctx.services.require(RegionApi).request_region(
                _REGION_KEY, self.ctx.tr("settings.region.annotate"), _REGION_COLOR
            )
        finally:
            self._calibrating = False

    # -- settings -----------------------------------------------------------------------------

    def create_settings_widget(self, parent: QWidget) -> QWidget:
        tr = self.ctx.tr
        panel = SettingsPanel(parent)
        hotkeys = self.ctx.services.require(HotkeyApi)
        basic = SettingSection(tr("settings.basic.title"))
        basic.addCards(
            HotkeySettingCard(
                hotkeys,
                hotkeys.binding(_CALIBRATE_REGION, HotkeyBinding(None)),
                lambda binding: hotkeys.set_binding(_CALIBRATE_REGION, binding),
                FluentIcon.SYNC,
                tr("settings.region.title"),
                tr("settings.region.content"),
                actions=[(tr("settings.region.button"), self._calibrate_region)],
            ),
            HotkeySettingCard(
                hotkeys,
                hotkeys.binding(_USE_ART, HotkeyBinding(None)),
                lambda binding: hotkeys.set_binding(_USE_ART, binding),
                FluentIcon.CALORIES,
                tr("settings.use_art.title"),
                tr("settings.use_art.content"),
            ),
        )
        advanced = SettingSection(tr("settings.advanced.title"))
        advanced.addCards(
            ConfigRangeCard(
                self.config.detect_delay_ms,
                FluentIcon.HISTORY,
                tr("settings.delay.title"),
                tr("settings.delay.content"),
                formatter=lambda value: f"{value} ms",
            ),
            ConfigRangeCard(
                self.config.match_threshold,
                FluentIcon.DEVELOPER_TOOLS,
                tr("settings.threshold.title"),
                tr("settings.threshold.content"),
                formatter=lambda value: f"{value / 1000:.3f}",
            ),
        )
        panel.addSection(basic)
        panel.addSection(advanced)
        return panel
