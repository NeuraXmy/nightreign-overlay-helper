"""Real self-down screenshots, image perturbations and bounded background sampling."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from nightreign_overlay.core.images import read_cv2_image
from nightreign_overlay.plugins.entertainment.self_detector import is_down
from tests.support.self_down_samples import continuous_variants, labeled_samples, legacy_variants, variants

_ROOT = Path(__file__).parents[1] / "data/entertainment/self_down"


@pytest.mark.parametrize(
    "name, expected, rgb",
    list(labeled_samples()),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_self_down_labeled_samples_and_combined_enhancements(name, expected, rgb):
    for parameters, image in variants(rgb):
        assert is_down(image) == expected, (name, parameters)


@pytest.mark.parametrize(
    "rgb", (np.zeros((7, 8, 3), np.uint8), np.zeros((32, 32), np.uint8), np.zeros((32, 32, 3)))
)
def test_self_down_invalid_input(rgb):
    with pytest.raises(ValueError):
        is_down(rgb)


@pytest.mark.parametrize("value", (0, 80, 255))
def test_self_down_uniform_background(value):
    assert not is_down(np.full((75, 76, 3), value, np.uint8))


@pytest.mark.parametrize("suffix", ["", "2", "3", "4"])
def test_self_down_real_samples_and_augmentations(suffix):
    rgb = cv2.cvtColor(read_cv2_image(_ROOT / f"down{suffix}.png"), cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    for parameters, image in legacy_variants(rgb):
        assert is_down(image), (suffix, parameters)
    background_suffix = suffix if suffix in ("", "2") else "2"
    game = cv2.cvtColor(read_cv2_image(_ROOT / f"game{background_suffix}.png"), cv2.COLOR_BGR2RGB)
    width, height = game.shape[1] - w + 1, game.shape[0] - h + 1
    for position in np.random.default_rng(20261023).choice(width * height, 10, replace=False):
        y, x = divmod(int(position), width)
        assert not is_down(game[y : y + h, x : x + w]), (suffix, x, y)


def test_continuous_progress_remains_down_through_segment_boundaries():
    rgb = cv2.cvtColor(read_cv2_image(_ROOT / "down2.png"), cv2.COLOR_BGR2RGB)
    failures = []
    total = 0
    for parameters, variant in continuous_variants(rgb):
        total += 1
        if not is_down(variant):
            failures.append(parameters)
    assert total == 5089
    assert not failures, failures[:10]
