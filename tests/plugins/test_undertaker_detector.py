from itertools import chain
from pathlib import Path

import cv2
import pytest

from nightreign_overlay.core.images import read_cv2_image
from nightreign_overlay.plugins.art_timer.undertaker_detector import is_active
from tests.support.undertaker_images import combined_variants, legacy_variants

_SAMPLES = Path(__file__).parents[1] / "data" / "undertaker_art"


@pytest.mark.parametrize("path", sorted(_SAMPLES.glob("*.png")), ids=lambda path: path.name)
def test_undertaker_active_icon_and_augmentations(path):
    rgb = cv2.cvtColor(read_cv2_image(path), cv2.COLOR_BGR2RGB)
    expected = path.name == "0.png"
    for parameters, image in chain(legacy_variants(rgb), combined_variants(rgb)):
        assert is_active(image) == expected, (path.name, parameters)
