"""Resource loading from Unicode installation directories."""

from shutil import copytree

import numpy as np
import pytest
from PIL import Image

from nightreign_overlay.plugins.art_timer.detector import ArtDetector
from nightreign_overlay.plugins.day_timer.detector import LANGUAGES, DayDetector
from nightreign_overlay.plugins.map_detect import detector as map_detector
from tests.support.paths import PROJECT_ROOT

PLUGINS = PROJECT_ROOT / "src/nightreign_overlay/plugins"


def test_timer_templates_load_from_unicode_paths(tmp_path):
    root = tmp_path / "黑夜助手 テスト"
    day_templates = copytree(PLUGINS / "day_timer/templates", root / "templates")
    art_icons = copytree(PLUGINS / "art_timer/icons", root / "icons")

    day_detector = DayDetector(day_templates)
    assert all(day_detector.available(language) for language in LANGUAGES)
    assert ArtDetector(art_icons).missing() == []


def test_map_background_loads_rgb_and_resizes_from_unicode_path(tmp_path, monkeypatch):
    path = tmp_path / "地图背景.png"
    Image.new("RGB", (10, 10), (11, 22, 33)).save(path)
    monkeypatch.setattr(map_detector, "get_data_path", lambda _: str(path))

    image = map_detector.open_cv2_image("maps/0.jpg", (4, 3))

    assert image.shape == (3, 4, 3)
    np.testing.assert_array_equal(image, np.broadcast_to((11, 22, 33), image.shape))


def test_invalid_map_background_reports_asset_path(tmp_path, monkeypatch):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"corrupt image")
    monkeypatch.setattr(map_detector, "get_data_path", lambda _: str(path))
    with pytest.raises(OSError, match="Cannot decode image") as error:
        map_detector.open_cv2_image("maps/0.jpg")
    assert str(path) in str(error.value)
