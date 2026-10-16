"""Asynchronous, bounded debug image and metadata storage."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage

from nightreign_overlay.core.config import ConfigItem
from nightreign_overlay.core.paths import user_data_dir

DEFAULT_KEEP = 10
DEFAULT_JPEG_QUALITY = 85


class DebugImageApi:
    """Submit diagnostic images without blocking detector threads."""

    def save(
        self,
        result_name: str,
        image: QImage | Image.Image | np.ndarray,
        meta: dict[str, Any] | None = None,
        *,
        keep: int = DEFAULT_KEEP,
        cooldown_seconds: float = 0,
    ) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class DebugImageService(DebugImageApi):
    """Write compressed JPG/JSON pairs under ``user_data_dir()/debug``."""

    def __init__(self, enabled: ConfigItem[bool]) -> None:
        self._enabled = enabled
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="debug-images")
        self._lock = threading.Lock()
        self._last_saved: dict[str, float] = {}
        self._closed = False

    def save(
        self,
        result_name: str,
        image: QImage | Image.Image | np.ndarray,
        meta: dict[str, Any] | None = None,
        *,
        keep: int = DEFAULT_KEEP,
        cooldown_seconds: float = 0,
    ) -> bool:
        if not self._enabled.value or self._closed or keep < 1:
            return False
        name = _safe_name(result_name)
        now = time.monotonic()
        with self._lock:
            previous = self._last_saved.get(name)
            if previous is not None and now - previous < max(0.0, cooldown_seconds):
                return False
            self._last_saved[name] = now
        snapshot = _copy_image(image)
        metadata = dict(meta or {})
        self._executor.submit(self._write, name, snapshot, metadata, max(1, keep))
        return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _write(
        self,
        name: str,
        image: QImage | Image.Image | np.ndarray,
        meta: dict[str, Any],
        keep: int,
    ) -> None:
        try:
            directory = user_data_dir() / "debug" / name
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = directory / f"{stamp}.jpg"
            _write_jpeg(path, image)
            if meta:
                path.with_suffix(".json").write_text(
                    json.dumps(_json_safe(meta), ensure_ascii=False, indent=2), encoding="utf-8"
                )
            self._prune(directory, keep)
        except Exception:
            # Diagnostics must never affect detection.  Avoid importing the logging stack here to keep
            # this small service usable during application shutdown as well.
            return

    @staticmethod
    def _prune(directory: Path, keep: int) -> None:
        images = sorted(directory.glob("*.jpg"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in images[keep:]:
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)


def _safe_name(name: str) -> str:
    value = "_".join(part for part in name.replace("\\", "/").split("/") if part not in ("", ".", ".."))
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value) or "result"


def _copy_image(image: QImage | Image.Image | np.ndarray) -> QImage | Image.Image | np.ndarray:
    if isinstance(image, QImage):
        return image.copy()
    if isinstance(image, Image.Image):
        return image.copy()
    return np.ascontiguousarray(image).copy()


def _write_jpeg(path: Path, image: QImage | Image.Image | np.ndarray) -> None:
    if isinstance(image, QImage):
        image.convertToFormat(QImage.Format.Format_RGB888).save(str(path), "JPG", DEFAULT_JPEG_QUALITY)
        return
    if isinstance(image, Image.Image):
        image.convert("RGB").save(path, "JPEG", quality=DEFAULT_JPEG_QUALITY, optimize=True)
        return
    array = np.asarray(image)
    if array.ndim == 2:
        encoded = array
    elif array.ndim == 3 and array.shape[2] == 4:
        encoded = cv2.cvtColor(array, cv2.COLOR_RGBA2BGR)
    elif array.ndim == 3 and array.shape[2] == 3:
        encoded = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
    else:
        raise ValueError(f"unsupported debug image shape: {array.shape}")
    if not cv2.imwrite(str(path), encoded, [cv2.IMWRITE_JPEG_QUALITY, DEFAULT_JPEG_QUALITY]):
        raise OSError(f"failed to write debug image {path}")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "getRect"):
        return list(value.getRect())
    if all(hasattr(value, name) and callable(getattr(value, name)) for name in ("x", "y")):
        return {"x": value.x(), "y": value.y()}
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
