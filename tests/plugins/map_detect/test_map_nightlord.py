"""Measure the current nightlord template matcher against checked-in captures."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from nightreign_overlay.plugins.map_detect.detector import MapDetector
from nightreign_overlay.plugins.map_detect.map_info import MapPattern
from tests.support.paths import MAP_CAPTURE_DIR

_CAPTURE_DIR = MAP_CAPTURE_DIR
_CAPTURES = sorted(_CAPTURE_DIR.glob("*.jpg"))


@dataclass(frozen=True)
class NightlordSampleResult:
    """One capture's independent labels and unmodified matcher output."""

    path: Path
    expected: frozenset[int | None]
    actual: int | None
    score: float

    @property
    def hidden(self) -> bool:
        return "hide" in self.path.stem.split("_")[1:]

    @property
    def correct(self) -> bool:
        return self.actual in self.expected


def _expected_nightlords(path: Path, patterns: dict[int, MapPattern]) -> frozenset[int | None]:
    """Hidden captures must match unk.png, regardless of the map's true boss."""
    if "hide" in path.stem.split("_")[1:]:
        return frozenset({None})
    pattern_ids = [int(value) for value in path.stem.split("_")[0].split("-")]
    return frozenset(patterns[identifier].nightlord for identifier in pattern_ids)


def _label(nightlord: int | None) -> str:
    return "unk.png (None)" if nightlord is None else f"ID={nightlord}"


@pytest.fixture(scope="module")
def nightlord_results() -> dict[Path, NightlordSampleResult]:
    """Evaluate every capture before assertions so each sample remains independently reportable."""
    assert _CAPTURES, f"No nightlord captures found in {_CAPTURE_DIR}"
    detector = MapDetector()
    patterns = {pattern.id: pattern for pattern in detector.info.patterns}
    results = {}
    for path in _CAPTURES:
        expected = _expected_nightlords(path, patterns)
        with Image.open(path) as image:
            rgb = np.array(image.convert("RGB"))
        # Use the original RGB map crop and the production resize/ROI/scales/templates.
        # No map recognition, POI voting, or map-ID-based fallback is involved.
        actual, score = detector._match_nightlord(rgb)
        results[path] = NightlordSampleResult(path, expected, actual, score)

    return results


@pytest.mark.parametrize("path", _CAPTURES, ids=lambda path: path.name)
def test_nightlord_capture_ground_truth(
    nightlord_results: dict[Path, NightlordSampleResult], path: Path
) -> None:
    """Keep every mismatch as a real failure, including hidden-to-visible misclassifications."""
    result = nightlord_results[path]
    assert math.isfinite(result.score), f"{path.name}: invalid template score {result.score}"
    assert result.correct, (
        f"{path.name}: expected={sorted(_label(value) for value in result.expected)}, "
        f"actual={_label(result.actual)}, score={result.score:.6f}"
    )
