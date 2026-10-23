from pathlib import Path

import cv2

from nightreign_overlay.plugins.entertainment.detector import detect_rgb

_SAMPLES = Path(__file__).parents[1] / "data" / "entertainment"


def test_low_fill_down_ring_remains_detected() -> None:
    for path in (_SAMPLES / "go_down_2").glob("*.png"):
        bgr = cv2.imread(str(path))
        assert bgr is not None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        upper, lower = detect_rgb(rgb)
        assert upper.present and upper.down, path.name
        assert lower.present and lower.down, path.name


def test_portraits_without_rings_are_not_reported_as_down() -> None:
    for name in ("0_0.png", "0_0(2).png"):
        bgr = cv2.imread(str(_SAMPLES / "go_down_3" / name))
        assert bgr is not None
        upper, lower = detect_rgb(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        assert upper.present and not upper.down, name
        assert lower.present and not lower.down, name


def test_all_sampled_down_states_match_filename() -> None:
    expected = {
        "0_0": (False, False),
        "0_n": (False, False),
        "1_0": (True, False),
        "1_1": (True, True),
        "1_2": (True, True),
        "2_2": (True, True),
        "3_0": (True, False),
        "3_3": (True, True),
    }
    for directory in ("go_down", "go_down_2", "go_down_3"):
        for path in (_SAMPLES / directory).glob("*.png"):
            stem = path.stem.split("(")[0]
            if stem not in expected:
                continue
            bgr = cv2.imread(str(path))
            assert bgr is not None
            upper, lower = detect_rgb(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            assert (upper.down, lower.down) == expected[stem], path


def test_single_teammate_skips_lower_row_entirely(monkeypatch):
    import numpy as np

    from nightreign_overlay.plugins.entertainment import detector

    rows = []
    expected = detector.Teammate(True, True, 3, 1.0, (10, 10))

    def detect_row(rgb, evidence, index):
        rows.append(index)
        return expected

    monkeypatch.setattr(detector, "_detect_row", detect_row)
    upper, lower = detector.detect_rgb(np.zeros((120, 240, 3), np.uint8), teammate_count=1)
    assert rows == [0]
    assert upper == expected and not lower.present and not lower.down
    rows.clear()
    detector.detect_rgb(np.zeros((120, 240, 3), np.uint8))
    assert rows == [0, 1]
