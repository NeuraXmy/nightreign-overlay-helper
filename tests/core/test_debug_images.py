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

    directory = root / "debug" / "地图识别"
    [path] = directory.glob("*.jpg")
    with Image.open(path) as saved:
        assert saved.size == (12, 10)
        np.testing.assert_allclose(saved.convert("RGB").getpixel((0, 0)), color, atol=3)
    assert json.loads(path.with_suffix(".json").read_text(encoding="utf-8")) == {"说明": "诊断截图"}
