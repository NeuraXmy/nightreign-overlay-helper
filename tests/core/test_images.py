"""Bundled images must decode under non-ASCII Windows installation paths."""

import cv2
import numpy as np
import pytest
from PIL import Image

from nightreign_overlay.core.images import read_cv2_image, write_cv2_image


@pytest.mark.parametrize("mode, flags", [("RGB", cv2.IMREAD_COLOR), ("RGBA", cv2.IMREAD_UNCHANGED)])
def test_read_image_from_unicode_path(tmp_path, mode, flags):
    path = tmp_path / "黑夜助手 テスト" / "模板.png"
    path.parent.mkdir()
    color = (11, 22, 33, 44) if mode == "RGBA" else (11, 22, 33)
    Image.new(mode, (5, 3), color).save(path)

    image = read_cv2_image(path, flags)

    expected = (33, 22, 11, 44) if mode == "RGBA" else (33, 22, 11)
    assert image.shape == (3, 5, len(expected))
    np.testing.assert_array_equal(image, np.broadcast_to(expected, image.shape))


@pytest.mark.parametrize("content", [b"", b"not an image"])
def test_invalid_image_reports_path(tmp_path, content):
    path = tmp_path / "broken.jpg"
    path.write_bytes(content)
    with pytest.raises(OSError, match="Cannot decode image") as error:
        read_cv2_image(path)
    assert str(path) in str(error.value)


def test_missing_image_reports_path(tmp_path):
    path = tmp_path / "missing.jpg"
    with pytest.raises(FileNotFoundError) as error:
        read_cv2_image(path)
    assert error.value.filename == str(path)


@pytest.mark.parametrize("channels", [1, 3, 4])
def test_write_image_to_unicode_path_preserves_pixels(tmp_path, channels):
    path = tmp_path / "用户目录 テスト" / "截图.png"
    path.parent.mkdir()
    shape = (5, 7) if channels == 1 else (5, 7, channels)
    pixels = np.random.default_rng(42).integers(0, 256, shape, dtype=np.uint8)

    write_cv2_image(path, pixels, [cv2.IMWRITE_PNG_COMPRESSION, 3])

    np.testing.assert_array_equal(read_cv2_image(path, cv2.IMREAD_UNCHANGED), pixels)
    assert list(path.parent.iterdir()) == [path]


def test_encode_failure_reports_path_and_preserves_existing_file(tmp_path):
    path = tmp_path / "invalid.png"
    path.write_bytes(b"original")
    with pytest.raises(OSError, match="Cannot encode image") as error:
        write_cv2_image(path, np.empty((0, 0), dtype=np.uint8))
    assert str(path) in str(error.value)
    assert path.read_bytes() == b"original"


def test_write_failure_reports_destination(tmp_path):
    path = tmp_path / "missing" / "image.jpg"
    with pytest.raises(FileNotFoundError) as error:
        write_cv2_image(path, np.zeros((3, 5, 3), dtype=np.uint8))
    assert error.value.filename == str(path)
