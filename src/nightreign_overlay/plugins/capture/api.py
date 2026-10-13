"""Public contract for the shared frame-capture plugin."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PyQt6.QtGui import QImage

_HDR_GAMMA = 2.2


@dataclass(frozen=True)
class FrameCaptured:
    """One immutable snapshot published once for a capture tick.

    ``hdr`` mirrors the shared "HDR image processing" setting at capture time. The image itself is left
    untouched: like the legacy app, each detector chooses its own processing (e.g. :func:`hdr_to_sdr`
    for template matching, raw pixels for colour sampling).
    """

    image: QImage
    captured_at: float
    hdr: bool = False


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


def make_frame(image: QImage, *, hdr: bool = False) -> FrameCaptured:
    """Detach the image from any native capture buffer before sharing it."""
    return FrameCaptured(image.copy(), time.monotonic(), hdr)


def hdr_to_sdr(image: np.ndarray) -> np.ndarray:
    """Legacy gamma tone mapping for uint8 RGB/BGR pixels captured in an HDR colour space."""
    return (np.power(image.astype(np.float32) / 255.0, 1.0 / _HDR_GAMMA) * 255).astype(np.uint8)
