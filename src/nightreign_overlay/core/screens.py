"""Coordinate mapping shared by calibration, capture and overlays.

Windows screen origins are already native desktop pixels. On macOS they are logical points: reserve
each screen's position at the largest desktop DPR, while keeping its own pixels unscaled. This leaves
gaps beside lower-DPR screens, but prevents their images from overlapping Retina neighbours.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QScreen


def capture_origin(origin: QPoint, desktop_ratio: float) -> QPoint:
    if sys.platform == "darwin":
        return QPoint(round(origin.x() * desktop_ratio), round(origin.y() * desktop_ratio))
    return QPoint(origin)


@dataclass(frozen=True)
class ScreenMapping:
    logical: QRect
    ratio: float
    origin: QPoint

    @property
    def pixels(self) -> QRect:
        return QRect(
            self.origin.x(),
            self.origin.y(),
            round(self.logical.width() * self.ratio),
            round(self.logical.height() * self.ratio),
        )

    def to_pixels(self, local: QRect) -> QRect:
        return QRect(
            self.origin.x() + round(local.x() * self.ratio),
            self.origin.y() + round(local.y() * self.ratio),
            round(local.width() * self.ratio),
            round(local.height() * self.ratio),
        )

    def to_logical(self, rect: QRect, *, truncate: bool = False) -> QRect:
        convert = int if truncate else round
        return QRect(
            self.logical.x() + convert((rect.x() - self.origin.x()) / self.ratio),
            self.logical.y() + convert((rect.y() - self.origin.y()) / self.ratio),
            max(1, convert(rect.width() / self.ratio)),
            max(1, convert(rect.height() / self.ratio)),
        )


def screen_mappings(screens: Sequence[QScreen]) -> list[ScreenMapping]:
    desktop_ratio = max((screen.devicePixelRatio() for screen in screens), default=1.0)
    return [
        ScreenMapping(
            screen.geometry(),
            screen.devicePixelRatio(),
            capture_origin(screen.geometry().topLeft(), desktop_ratio),
        )
        for screen in screens
    ]


def mapping_for_rect(rect: QRect, screens: Sequence[QScreen]) -> ScreenMapping:
    mappings = screen_mappings(screens)
    return next(
        (mapping for mapping in mappings if mapping.pixels.contains(rect.topLeft())),
        mappings[0] if mappings else ScreenMapping(QRect(), 1.0, QPoint()),
    )
