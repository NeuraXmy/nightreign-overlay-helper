"""Real self-down screenshots, image perturbations and bounded background sampling."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from nightreign_overlay.core.images import read_cv2_image
from nightreign_overlay.plugins.entertainment.self_detector import is_down

_ROOT = Path(__file__).parents[1] / "data/entertainment/self_down"


@pytest.mark.parametrize("suffix", ["", "2", "3", "4"])
def test_self_down_real_samples_and_augmentations(suffix):
    rgb = cv2.cvtColor(read_cv2_image(_ROOT / f"down{suffix}.png"), cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    variants = [rgb, cv2.GaussianBlur(rgb, (7, 7), 2)]
    for saturation in (0.5, 1, 1.5):
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1].astype(float) * saturation, 0, 255)
        colored = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(float)
        for contrast in (0.6, 1, 1.4):
            for brightness in (0.6, 1, 1.4):
                variants.append(
                    np.clip(((colored - 127.5) * contrast + 127.5) * brightness, 0, 255).astype(np.uint8)
                )
    variants.append(cv2.addWeighted(rgb, 1.8, cv2.GaussianBlur(rgb, (5, 5), 1), -0.8, 0))
    for size in (48, 80, 160, 230):
        variants.append(cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA))
    for dx in (-5, 0, 5):
        for dy in (-5, 0, 5):
            variants.append(
                cv2.warpAffine(
                    rgb, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), borderMode=cv2.BORDER_REFLECT
                )
            )
    for i, image in enumerate(variants):
        assert is_down(image), (suffix, i)
    background_suffix = suffix if suffix in ("", "2") else "2"
    game = cv2.cvtColor(read_cv2_image(_ROOT / f"game{background_suffix}.png"), cv2.COLOR_BGR2RGB)
    width, height = game.shape[1] - w + 1, game.shape[0] - h + 1
    for position in np.random.default_rng(20261023).choice(width * height, 10, replace=False):
        y, x = divmod(int(position), width)
        assert not is_down(game[y : y + h, x : x + w]), (suffix, x, y)


def test_continuous_progress_remains_down_through_segment_boundaries():
    from tests.support.self_down_samples import continuous_progress

    rgb = cv2.cvtColor(read_cv2_image(_ROOT / "down2.png"), cv2.COLOR_BGR2RGB)
    failures = []
    total = 0
    for degrees, image in continuous_progress(rgb):
        hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = (hsv[..., 1].astype(float) * 0.5).astype(np.uint8)
        low_sat = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
        variants = {
            "original": image,
            "dim": np.clip(image.astype(float) * 0.6, 0, 255).astype(np.uint8),
            "bright": np.clip(image.astype(float) * 1.4, 0, 255).astype(np.uint8),
            "low_saturation": low_sat,
            "clipped": np.clip(((low_sat.astype(float) - 127.5) * 1.4 + 127.5) * 1.4, 0, 255).astype(
                np.uint8
            ),
            "blur": cv2.GaussianBlur(image, (7, 7), 2),
            "offset": cv2.warpAffine(
                image,
                np.float32([[1, 0, 5], [0, 1, -5]]),
                (image.shape[1], image.shape[0]),
                borderMode=cv2.BORDER_REFLECT,
            ),
        }
        for name, variant in variants.items():
            total += 1
            if not is_down(variant):
                failures.append((float(degrees), name))
    assert total == 5089
    assert not failures, failures[:10]
