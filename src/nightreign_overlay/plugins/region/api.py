"""Public contract for selecting and storing screen rectangles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QRect
from PyQt6.QtGui import QColor, QEnterEvent, QHideEvent, QImage, QShowEvent
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, FluentIcon, IconWidget, ToolTipFilter

from nightreign_overlay.core.i18n import tr
from nightreign_overlay.core.services import ServiceRegistry


@dataclass(frozen=True)
class RegionTarget:
    """One annotation button of the selector, e.g. "click and box the normal HP bar".

    ``color`` is the button and rectangle colour; ``None`` uses the selector's default colour.
    """

    id: str
    label: str
    color: str | None = None


class RegionApi:
    def request_region(
        self,
        key: str,
        label: str | None = None,
        color: str | None = None,
        *,
        screenshot_path: str | None = None,
    ) -> QRect | None:
        """Interactively select one global-pixel rectangle and persist it under ``key``.

        ``label`` is the text of the selector's annotation button, e.g. "click and box the DAY I icon";
        ``color`` overrides the default annotation colour. ``screenshot_path`` optionally saves
        the annotated screen at the moment of confirmation, like the legacy calibration diagnostics.
        """
        raise NotImplementedError

    def request_samples(self, targets: Sequence[RegionTarget]) -> dict[str, QImage] | None:
        """Freeze the screen, let the user box any of ``targets`` and return the frozen pixels of each box.

        Only boxed targets appear in the result and nothing is persisted. Returns ``None`` when the user
        cancels or the screen cannot be frozen (e.g. missing screen-capture permission).
        """
        raise NotImplementedError

    def region(self, key: str) -> QRect | None:
        raise NotImplementedError

    def clear_region(self, key: str) -> None:
        """Forget the rectangle stored under ``key`` so it has to be calibrated again."""
        raise NotImplementedError

    def show_preview(self, key: str, color: str | None = None) -> bool:
        """Outline the rectangle stored under ``key`` on screen in the shared click-through preview window.

        ``color`` is the outline colour (the selector's default when ``None``). Returns ``False`` and
        hides the preview when ``key`` has not been calibrated.
        """
        raise NotImplementedError

    def hide_preview(self) -> None:
        raise NotImplementedError

    def save_region(self, key: str, rect: QRect) -> None:
        """Persist a rectangle without opening the platform UI."""
        raise NotImplementedError

    def save_region_for_test(self, key: str, rect: QRect) -> None:
        """Compatibility alias for existing integrations."""
        self.save_region(key, rect)


class RegionStatus(QWidget):
    """Calibration status (eye icon plus "calibrated" / "not calibrated") with an on-screen hover preview.

    While hovered, the calibrated region is outlined on screen. The service is looked up on every refresh
    because settings pages are built before ``region`` activates.
    """

    #: Fluent success / caution text colours for the light and the dark theme.
    _CALIBRATED_COLORS = (QColor("#0f7b0f"), QColor("#6ccb5f"))
    _UNCALIBRATED_COLORS = (QColor("#9d5d00"), QColor("#fce100"))

    def __init__(
        self, services: ServiceRegistry, key: str, color: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._key = key
        self._color = color
        self.icon = IconWidget(FluentIcon.VIEW, self)
        self.icon.setFixedSize(16, 16)
        self.label = CaptionLabel(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.icon)
        layout.addWidget(self.label)
        self.installEventFilter(ToolTipFilter(self, showDelay=300))
        self.refresh()

    @property
    def calibrated(self) -> bool:
        return self._rect() is not None

    def _rect(self) -> QRect | None:
        regions = self._services.get(RegionApi)
        return regions.region(self._key) if regions is not None else None

    def refresh(self) -> None:
        """Re-read the stored region, e.g. after calibrating or resetting the page."""
        rect = self._rect()
        if rect is None:
            self.label.setText(tr("region_preview.uncalibrated"))
            self.label.setTextColor(*self._UNCALIBRATED_COLORS)
            self.setToolTip(tr("region_preview.unset"))
        else:
            self.label.setText(tr("region_preview.calibrated"))
            self.label.setTextColor(*self._CALIBRATED_COLORS)
            self.setToolTip(
                tr("region_preview.current", x=rect.x(), y=rect.y(), width=rect.width(), height=rect.height())
            )

    def showEvent(self, event: QShowEvent | None) -> None:
        # Calibration hides and re-shows the main window, and hotkey calibration may run while it is hidden.
        super().showEvent(event)
        self.refresh()

    def enterEvent(self, event: QEnterEvent | None) -> None:
        super().enterEvent(event)
        # The filter reads the tooltip only when it is shown, so it picks up the refreshed text.
        self.refresh()
        if (regions := self._services.get(RegionApi)) is not None:
            regions.show_preview(self._key, self._color)

    def leaveEvent(self, event: QEvent | None) -> None:
        super().leaveEvent(event)
        self._hide_preview()

    def hideEvent(self, event: QHideEvent | None) -> None:
        # Switching pages hides the icon without a leave event; the preview must not stay behind.
        super().hideEvent(event)
        self._hide_preview()

    def _hide_preview(self) -> None:
        if (regions := self._services.get(RegionApi)) is not None:
            regions.hide_preview()
