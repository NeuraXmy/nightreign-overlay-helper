"""Temporal confirmation of scanline boundaries without retaining captured images."""

from __future__ import annotations

from collections import deque

import numpy as np

from nightreign_overlay.plugins.hp_marker.structural import _calibrate, _Reference, estimate_boundary

_WINDOW = 5
_MIN_SUPPORT = 4
_EXPIRE_AFTER = 2 * _WINDOW


class StructuralHpDetector:
    """Confirm stationary caps, but require fresh image evidence for every output.

    A moving fill/damage cap and scene edges are not reliable HP endpoints. A
    short history of relative ridge responses distinguishes them from a narrow,
    neutral outer cap. Broader caps and limit-loss divisions still use the
    multiscale estimator, with temporal and local shape confirmation.
    """

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._shape: tuple[int, ...] | None = None
        self._profiles: deque[np.ndarray] = deque(maxlen=_WINDOW)
        self._scene: deque[np.ndarray] = deque(maxlen=_WINDOW)
        self._colors: deque[float] = deque(maxlen=_WINDOW)
        self._boundaries: deque[int | None] = deque(maxlen=_WINDOW)
        self._length: int | None = None
        self._narrow = False
        self._misses = 0

    def detect(self, image: np.ndarray) -> int | None:
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            self._reset()
            return None
        if image.shape != self._shape:
            self._reset()
            self._shape = image.shape
        if image.shape[0] < 1 or image.shape[1] < 48:
            self._reset()
            return None
        row = image[image.shape[0] // 2]
        reference = _calibrate(row)
        if reference is None:
            # A vanished HUD or invalid start cap cannot contribute old evidence
            # to a new acquisition, even when its image dimensions are unchanged.
            self._reset()
            return None

        response, profile, color = _cap_profile(row, reference)
        self._profiles.append(profile)
        self._scene.append(row.mean(axis=1) / reference.contrast)
        self._colors.append(color)
        primary = None
        # Once a narrow cap is confirmed, verification needs only the response
        # above; avoid running the more expensive multiscale scan on every frame.
        if self._length is None or not self._narrow:
            primary = estimate_boundary(image).length
            supported = primary is not None and _has_boundary_shape(row, primary, reference)
            self._boundaries.append(primary if supported else None)
        else:
            self._boundaries.append(None)

        candidate = self._candidate()
        if self._length is None:
            self._acquire(primary, candidate, reference)
        if self._length is None:
            return None
        if candidate is not None and abs(candidate - self._length) <= 3:
            self._narrow = True

        if self._narrow:
            # A pixel of antialiasing or compression may move the cap's peak.
            verified = float(response[self._length - 2 : self._length + 3].max()) >= 0.08
        else:
            verified = (
                primary is not None and self._boundaries[-1] is not None and abs(primary - self._length) <= 3
            )
        if verified:
            self._misses = 0
            return self._length
        self._misses += 1
        if self._misses >= _EXPIRE_AFTER:
            self._length = None
            self._narrow = False
            self._misses = 0
        return None

    def _candidate(self) -> int | None:
        if len(self._profiles) < _WINDOW:
            return None
        # The lower quartile requires a response in at least four of five
        # observations. Moving scene texture does not accumulate positive votes.
        profile = np.quantile(np.stack(self._profiles), 0.25, axis=0)
        x = int(profile.argmax())
        strength = float(profile[x])
        threshold = 0.16 if float(np.median(self._colors)) < 10 else 0.25
        profile[max(0, x - 5) : x + 6] = 0
        if strength > threshold and strength > 1.5 * max(0, float(profile.max())):
            scene = np.stack(self._scene)[:, x + 6 : x + 70]
            # Persistence provides evidence only when surrounding pixels change.
            # An unchanging image cannot distinguish a static internal fill cap
            # from an outer cap; leave those cases to the structural estimator.
            if scene.shape[1] >= 16 and float(np.median(np.ptp(scene, axis=0))) > 0.015:
                return x
        return None

    def _acquire(self, primary: int | None, candidate: int | None, reference: _Reference) -> None:
        valid = [value for value in self._boundaries if value is not None]
        if len(self._boundaries) == _WINDOW and len(valid) >= _MIN_SUPPORT and max(valid) - min(valid) <= 3:
            self._length = int(np.median(valid))
            self._narrow = False
        elif candidate is not None:
            # A nearby earlier division may be a gray limit-loss boundary. Do
            # not replace usable HP with the outer end of that gray segment.
            ambiguous_limit = primary is not None and 0 < candidate - primary < 8 * reference.scale
            if not ambiguous_limit:
                self._length = candidate
                self._narrow = True


def _cap_profile(row: np.ndarray, reference: _Reference) -> tuple[np.ndarray, np.ndarray, float]:
    rgb = row.astype(np.float64)
    gray = rgb.mean(axis=1)
    chroma = np.ptp(rgb, axis=1)
    stop = min(64, len(row) // 3)
    color = float(np.median(chroma[8:stop]))
    smoothed = (np.roll(gray, 1) + gray + np.roll(gray, -1)) / 3
    # A narrow ridge must rise above BOTH sides; a bright scene step is not a cap.
    ridge = gray - np.maximum(np.roll(smoothed, 3), np.roll(smoothed, -3))
    response = ridge / reference.contrast * np.clip(1 - chroma / max(color, 10), 0, 1)
    response[: max(16, 3 * reference.scale)] = 0
    response[-max(8, 2 * reference.scale) :] = 0
    profile = response.copy()
    # Acquiring a colored damage cap is unsafe. Verification is more permissive
    # after the neutral outer cap has been established across multiple frames.
    profile[chroma > max(6, 0.2 * color)] = 0
    return response, profile, color


def _has_boundary_shape(row: np.ndarray, x: int, reference: _Reference) -> bool:
    rgb = row.astype(np.float64)
    gray = rgb.mean(axis=1)
    chroma = np.ptp(rgb, axis=1)
    span = reference.scale
    inner = max(1, span // 3)
    left, right = chroma[max(0, x - span) : x - inner], chroma[x + inner : x + span]
    if not len(left) or not len(right) or x + 8 > len(row):
        return False
    left_color, right_color = float(np.median(left)), float(np.median(right))
    start_color = float(np.median(chroma[8 : min(64, len(row) // 3)]))
    color_division = abs(left_color - right_color) > 0.5 * start_color and min(
        left_color, right_color
    ) < 0.25 * max(left_color, right_color)
    falling_cap = (
        float(gray[max(0, x - 2) : x + 4].max() - gray[x + 2 : x + 8].min()) > 0.15 * reference.contrast
    )
    return color_division or falling_cap
