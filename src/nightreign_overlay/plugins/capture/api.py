"""Public contract for the shared frame-capture plugin."""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np
from PyQt6.QtCore import QRect
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

    def hdr_enabled(self) -> bool:
        """Current shared "HDR image processing" setting, for features that keep separate HDR settings."""
        raise NotImplementedError


def make_frame(image: QImage, *, hdr: bool = False) -> FrameCaptured:
    """Detach the image from any native capture buffer before sharing it."""
    return FrameCaptured(image.copy(), time.monotonic(), hdr)


def crop_rgb(frame: QImage, region: QRect | None = None) -> np.ndarray | None:
    """Copy ``region`` (default: the whole image) of ``frame`` into an ``(h, w, 3)`` uint8 RGB array.

    The part outside the frame is dropped; ``None`` is returned when nothing remains.
    """
    region = frame.rect() if region is None else region.intersected(frame.rect())
    if region.isEmpty():
        return None
    crop = frame.copy(region).convertToFormat(QImage.Format.Format_RGB888)
    ptr = crop.bits()
    ptr.setsize(crop.sizeInBytes())
    # Rows are padded to 4-byte boundaries, so slice each scanline before splitting channels.
    rows = np.frombuffer(ptr, np.uint8).reshape(crop.height(), crop.bytesPerLine())
    return rows[:, : crop.width() * 3].reshape(crop.height(), crop.width(), 3).copy()


def hdr_to_sdr(image: np.ndarray) -> np.ndarray:
    """Legacy gamma tone mapping for uint8 RGB/BGR pixels captured in an HDR colour space."""
    return (np.power(image.astype(np.float32) / 255.0, 1.0 / _HDR_GAMMA) * 255).astype(np.uint8)


def resize_to_height(image: np.ndarray, height: int) -> np.ndarray:
    """Scale to ``height`` keeping the aspect ratio, like the legacy ``resize_by_height_keep_aspect_ratio``.

    Downscaling uses area averaging, the closest OpenCV match to the legacy anti-aliased PIL LANCZOS filter.
    """
    width = max(1, int(image.shape[1] * height / image.shape[0]))
    interpolation = cv2.INTER_AREA if image.shape[0] > height else cv2.INTER_LANCZOS4
    return cv2.resize(image, (width, height), interpolation=interpolation)


def normalize_image(image: np.ndarray) -> np.ndarray:
    """Legacy map HDR normalization: LAB luminance CLAHE, without altering the shared frame."""
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    luminance, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    normalized = cv2.merge([clahe.apply(luminance), a, b])
    return cv2.cvtColor(normalized, cv2.COLOR_LAB2RGB)
