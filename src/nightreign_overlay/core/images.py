"""Image encoding and decoding through Python file I/O for Unicode paths on Windows."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def read_cv2_image(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """Read an image, raising an informative OSError if it cannot be decoded."""
    path = Path(path)
    encoded = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    try:
        image = cv2.imdecode(encoded, flags) if encoded.size else None
    except cv2.error as exc:
        raise OSError(f"Cannot decode image: {path}") from exc
    if image is None or image.size == 0:
        raise OSError(f"Cannot decode image: {path}")
    return image


def write_cv2_image(path: str | Path, image: np.ndarray, params: list[int] | None = None) -> None:
    """Encode an OpenCV image and write it without native filename handling."""
    path = Path(path)
    try:
        success, encoded = cv2.imencode(path.suffix, image, params or [])
    except cv2.error as exc:
        raise OSError(f"Cannot encode image: {path}") from exc
    if not success:
        raise OSError(f"Cannot encode image: {path}")
    path.write_bytes(encoded.tobytes())
