"""Regression checks for the expanded-region experiment, separate from production."""

import numpy as np
from PIL import Image

from tests.support.hp_rectangle import RectangleHpExperiment
from tests.support.hp_video import VIDEO_ROOT


def _frame() -> np.ndarray:
    return np.asarray(Image.open(VIDEO_ROOT / "rectangle_length_3_frame_0.png").convert("RGB"))


def test_experiment_uses_rectangle_margin_and_does_not_modify_input():
    source = _frame()
    original = source.copy()
    detector = RectangleHpExperiment()
    outputs = [detector.detect(source) for _ in range(8)]
    assert outputs[:4] == [None] * 4
    assert outputs[-1] is not None and abs(outputs[-1] - 425) <= 3
    assert detector.box is not None
    assert detector.box[0] == 10
    assert np.array_equal(source, original)


def test_vanished_hud_resets_geometry_and_requires_new_confirmation():
    frame = _frame()
    detector = RectangleHpExperiment()
    for _ in range(8):
        detector.detect(frame)
    assert detector.detect(np.zeros_like(frame)) is None
    assert detector.box is None
    assert [detector.detect(frame) for _ in range(4)] == [None] * 4
    assert detector.detect(frame) is not None


def test_expanded_region_can_move_without_moving_the_measured_length():
    source = _frame()
    shifted = np.zeros_like(source)
    shifted[2:, 5:] = source[:-2, :-5]
    detector = RectangleHpExperiment()
    outputs = [detector.detect(shifted) for _ in range(8)]
    assert outputs[-1] is not None and abs(outputs[-1] - 425) <= 3
    assert detector.box is not None and detector.box[0] == 15


def test_size_change_resets_confirmation_and_invalid_input_is_rejected():
    frame = _frame()
    detector = RectangleHpExperiment()
    for _ in range(8):
        detector.detect(frame)
    assert detector.detect(frame[:, :-1]) is None
    assert detector.detect(frame.astype(np.float32)) is None
    assert detector.detect(np.zeros((3, 3), dtype=np.uint8)) is None
