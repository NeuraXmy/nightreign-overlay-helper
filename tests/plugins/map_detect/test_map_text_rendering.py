"""Map label width, anchors and language-specific rendering settings."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

from nightreign_overlay.plugins.map_detect import detector as detector_module
from nightreign_overlay.plugins.map_detect.config import MapDetectionSettings
from nightreign_overlay.plugins.map_detect.detector import MapDetector, MapPatternMatchResult
from nightreign_overlay.plugins.map_detect.image_utils import draw_text, get_font, get_text_size


@pytest.mark.parametrize("align", ["c", "lt", "lb"])
@pytest.mark.parametrize("width_scale", [0.1, 0.5, 0.75])
def test_text_width_changes_without_changing_height_or_anchor(align, width_scale):
    images = [Image.new("RGBA", (1000, 200)) for _ in range(2)]
    for image, scale in zip(images, (1.0, width_scale), strict=True):
        draw_text(
            image,
            (500, 100),
            "Red Wolf of the King Consort",
            24,
            (255, 255, 255, 255),
            2,
            align=align,
            width_scale=scale,
        )
    original, scaled = [image.getchannel("A").getbbox() for image in images]
    assert scaled[1::2] == original[1::2]
    assert abs((scaled[2] - scaled[0]) - round((original[2] - original[0]) * width_scale)) <= 3
    if align == "c":
        assert abs((scaled[0] + scaled[2]) - (original[0] + original[2])) <= 3
    else:
        assert abs(scaled[0] - original[0]) <= 2


@pytest.mark.parametrize("align", ["c", "lt", "lb"])
def test_full_width_keeps_original_text_rendering(align):
    actual = Image.new("RGBA", (600, 200))
    expected = actual.copy()
    pos, text, size = (250, 100), "Black Knife Assassin", 24
    font = get_font(size)
    width, height = get_text_size(font, text)
    x, y = pos
    if align == "lb":
        x, y = x + width // 2, y - height // 2
    elif align == "lt":
        x, y = x + width // 2, y + height // 2
    ImageDraw.Draw(expected).text(
        (x - width // 2, y - height // 2),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    )
    draw_text(actual, pos, text, size, (255, 255, 255, 255), 2, align=align, width_scale=1.0)
    np.testing.assert_array_equal(np.array(actual), np.array(expected))


def test_long_labels_are_compressed_before_clipping_at_map_edges():
    reference = Image.new("RGBA", (1000, 200))
    clipped = Image.new("RGBA", (100, 80))
    for image, pos in ((reference, (405, 100)), (clipped, (5, 40))):
        draw_text(
            image,
            pos,
            "Draconic Tree Sentinel & Royal Cavalrymen",
            24,
            (255, 255, 255, 255),
            2,
            width_scale=0.5,
        )
    np.testing.assert_array_equal(np.array(clipped), np.array(reference.crop((400, 60, 500, 140))))


@pytest.mark.parametrize(
    ("language", "percent", "expected_scale"),
    [
        ("en_US", 50, 0.5),
        ("en_US", 75, 0.75),
        ("en_US", 100, 1.0),
        ("zh_CN", 50, 1.0),
        ("ja_JP", 50, 1.0),
        ("zh_TW", 50, 1.0),
    ],
)
def test_only_english_landmark_labels_use_configured_width(monkeypatch, language, percent, expected_scale):
    detector = MapDetector(MapDetectionSettings(english_text_width_percent=percent), language=language)
    pattern = next(p for p in detector.info.patterns if p.earth_shifting == 4)
    drawn = []
    monkeypatch.setattr(
        detector_module,
        "draw_text",
        lambda _img, *args, **kwargs: drawn.append((args, kwargs["width_scale"])),
    )
    result = MapPatternMatchResult(pattern=pattern, nightlord=pattern.nightlord, score=0, error=0)
    detector._draw_overlay_image(result, (750, 750), 0)
    labels = [scale for args, scale in drawn if len(args) == 6]
    descriptions = [scale for args, scale in drawn if len(args) == 7]
    assert labels and all(scale == expected_scale for scale in labels)
    assert len(descriptions) >= 2 and all(scale == 1.0 for scale in descriptions)
