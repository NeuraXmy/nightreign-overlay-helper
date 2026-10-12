"""Public contract for the shared frame-capture plugin."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtGui import QImage


@dataclass(frozen=True)
class FrameCaptured:
    """One immutable snapshot published once for a capture tick."""

    image: QImage
    captured_at: float


class CaptureApi:
    """Read the latest game frame or request a fresh capture.

    Consumers should normally subscribe to :class:`FrameCaptured`; this avoids every detector capturing and
    converting the same frame independently.
    """

    def latest_frame(self) -> FrameCaptured | None:
        raise NotImplementedError

    def capture_now(self) -> FrameCaptured | None:
        """Capture one frame immediately without starting the continuous stream."""
        raise NotImplementedError

    def acquire_stream(self, owner: str) -> None:
        """Request periodic shared frames under ``owner`` until :meth:`release_stream` is called."""
        raise NotImplementedError

    def release_stream(self, owner: str) -> None:
        """Release one periodic-frame request made under ``owner``."""
        raise NotImplementedError


def make_frame(image: QImage) -> FrameCaptured:
    """Detach the image from any native capture buffer before sharing it."""
    return FrameCaptured(image.copy(), time.monotonic())
