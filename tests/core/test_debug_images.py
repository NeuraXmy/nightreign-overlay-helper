"""Diagnostic images and metadata survive Unicode user data paths."""

import json

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtGui import QColor, QImage

from nightreign_overlay.core import debug as debug_module
from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.debug import DebugImageService


@pytest.mark.parametrize("kind", ["rgb", "rgba", "gray", "pil", "qt"])
def test_async_debug_images_and_metadata_in_unicode_directory(store, tmp_path, monkeypatch, kind):
    root = tmp_path / "中文用户 テスト"
    monkeypatch.setattr(debug_module, "user_data_dir", lambda: root)
    config = store.bind(AppConfig, "app")
    service = DebugImageService(config.debug_images_enabled)
    color = (20, 70, 130)
    if kind == "qt":
        image = QImage(12, 10, QImage.Format.Format_RGB32)
        image.fill(QColor(*color))
    elif kind == "pil":
        image = Image.new("RGBA", (12, 10), (*color, 255))
    elif kind == "gray":
        image = np.full((10, 12), 70, dtype=np.uint8)
        color = (70, 70, 70)
    else:
        image = np.empty((10, 12, 4 if kind == "rgba" else 3), dtype=np.uint8)
        image[:] = (*color, 255) if kind == "rgba" else color
    try:
        assert service.save("地图识别", image, {"说明": "诊断截图"})
    finally:
        service.close()
        # close has a time budget; explicitly drain before checking asynchronous output.
        service._executor.shutdown(wait=True)

    directory = root / "debug" / "地图识别"
    [path] = directory.glob("*.jpg")
    with Image.open(path) as saved:
        assert saved.size == (12, 10)
        np.testing.assert_allclose(saved.convert("RGB").getpixel((0, 0)), color, atol=3)
    assert json.loads(path.with_suffix(".json").read_text(encoding="utf-8")) == {"说明": "诊断截图"}


def test_queue_is_bounded_and_close_does_not_wait_for_blocked_writer(store, monkeypatch):
    import threading
    import time

    entered, release = threading.Event(), threading.Event()
    config = store.bind(AppConfig, "app")
    service = DebugImageService(config.debug_images_enabled)

    def blocked(*args):
        entered.set()
        release.wait(5)

    monkeypatch.setattr(service, "_write", blocked)
    monkeypatch.setattr(debug_module, "CLOSE_TIMEOUT_SECONDS", 0.01)
    image = np.zeros((10, 12, 3), dtype=np.uint8)
    try:
        assert service.save("test", image, keep=1)
        assert entered.wait(2)
        accepted = sum(service.save("test", image, keep=1) for _ in range(64))
        assert accepted == debug_module.MAX_PENDING_IMAGES - 1
        start = time.monotonic()
        service.close()
        assert time.monotonic() - start < 1
        assert not service.save("test", image)
        assert len(service._pending) <= 1
    finally:
        release.set()
        service._executor.shutdown(wait=True, cancel_futures=True)


def test_oversized_snapshot_is_rejected_before_copy(store, monkeypatch):
    config = store.bind(AppConfig, "app")
    service = DebugImageService(config.debug_images_enabled)
    monkeypatch.setattr(debug_module, "MAX_PENDING_BYTES", 10)
    try:
        assert not service.save("huge", np.zeros((10, 10, 3), dtype=np.uint8))
        assert not service._pending
    finally:
        service.close()
