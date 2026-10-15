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

_CAPTURE_DIR = Path(__file__).parent / "data" / "map_detect"
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
def nightlord_results(pytestconfig: pytest.Config) -> dict[Path, NightlordSampleResult]:
    """Evaluate every capture before reporting, so failures cannot truncate the accuracy report."""
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

    reporter = pytestconfig.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "Nightlord template matching accuracy")
        for title, samples in (
            ("overall", list(results.values())),
            ("visible", [result for result in results.values() if not result.hidden]),
            ("hidden (unk.png)", [result for result in results.values() if result.hidden]),
        ):
            correct = sum(result.correct for result in samples)
            accuracy = f"{correct / len(samples):.2%}" if samples else "N/A"
            reporter.write_line(f"{title}: {correct}/{len(samples)} = {accuracy}")
        for result in results.values():
            expected_labels = " | ".join(sorted(_label(value) for value in result.expected))
            reporter.write_line(
                f"{'PASS' if result.correct else 'FAIL'} {result.path.name}: "
                f"expected={expected_labels}; actual={_label(result.actual)}; score={result.score:.6f}"
            )
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
