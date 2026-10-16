"""Wait for a complete map to stop fading before consuming its recognition request."""

from __future__ import annotations

import math

import cv2
import numpy as np

_SAMPLE_SIZE = 96
_BLOCKS = 4
_CHANGE_THRESHOLD = 2.0
_STABLE_SECONDS = 0.6
_MIN_SAMPLES = 3
# The shared capture interval can be as long as two seconds. Longer gaps do not
# provide continuous observations, even when the two endpoint images agree.
_MAX_GAP_SECONDS = 2.5


def map_stability_sample(image: np.ndarray) -> np.ndarray:
    """Keep raw luminance in the central 80%; contrast normalization hides fades."""
    height, width = image.shape[:2]
    margin_y, margin_x = height // 10, width // 10
    center = image[margin_y : height - margin_y, margin_x : width - margin_x]
    gray = cv2.cvtColor(center, cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, (_SAMPLE_SIZE, _SAMPLE_SIZE), interpolation=cv2.INTER_AREA)


def _changed(first: np.ndarray, second: np.ndarray, threshold: float = _CHANGE_THRESHOLD) -> bool:
    difference = np.abs(first.astype(np.float32) - second)
    side = _SAMPLE_SIZE // _BLOCKS
    blocks = difference.reshape(_BLOCKS, side, _BLOCKS, side).mean(axis=(1, 3))
    # Local cursors/markers may animate; fades change most of the map's blocks.
    return bool(np.median(blocks) > threshold)


class MapStability:
    """Require several full-map observations over a configurable stable interval."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._anchor: np.ndarray | None = None
        self._previous: np.ndarray | None = None
        self._started_at = 0.0
        self._last_at: float | None = None
        self._samples = 0
        self._parameters: tuple[float, float] | None = None

    def observe(
        self,
        sample: np.ndarray | None,
        captured_at: float,
        full_map: bool,
        change_threshold: float = _CHANGE_THRESHOLD,
        stable_seconds: float = _STABLE_SECONDS,
    ) -> bool:
        """Use capture timestamps, never worker completion times, to measure stability."""
        parameters = change_threshold, stable_seconds
        if self._parameters is not None and self._parameters != parameters:
            self.reset()
        self._parameters = parameters
        if not full_map or sample is None or not math.isfinite(captured_at):
            self.reset()
            return False
        if self._last_at is not None and captured_at <= self._last_at:
            self.reset()
            return False
        if self._last_at is not None and captured_at - self._last_at > _MAX_GAP_SECONDS:
            self.reset()
        if (
            self._anchor is None
            or _changed(sample, self._previous, change_threshold)
            or _changed(sample, self._anchor, change_threshold)
        ):
            self._anchor = sample.copy()
            self._started_at = captured_at
            self._samples = 0
        self._previous = sample.copy()
        self._last_at = captured_at
        self._samples += 1
        return self._samples >= _MIN_SAMPLES and captured_at - self._started_at >= stable_seconds
