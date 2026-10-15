"""HP boundaries from a single horizontal RGB scanline and horizontal scale consensus."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image, ImageFilter


@dataclass(frozen=True)
class BoundaryEstimate:
    length: int | None
    reason: str


@dataclass(frozen=True)
class _Reference:
    scale: int
    baseline: float
    contrast: float


def estimate_boundary(image: np.ndarray) -> BoundaryEstimate:
    """Read only the center row; reject ambiguous boundaries rather than guessing.

    The crop starts at the bar's left cap. No fixed hue/palette, crop-height
    measurement, previous length, or pixels above/below the center row are used.
    """
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        return BoundaryEstimate(None, "invalid_rgb_input")
    if image.shape[0] < 1 or image.shape[1] < 48:
        return BoundaryEstimate(None, "insufficient_context")
    row = image[image.shape[0] // 2]
    reference = _calibrate(row)
    if reference is None:
        return BoundaryEstimate(None, "no_coherent_start_cap")

    # Blur the extracted row horizontally: vertical padding cannot affect any scale.
    source = Image.fromarray(row[None])
    estimates = []
    for radius in (0.0, 0.6, 1.2):
        view = source.filter(ImageFilter.GaussianBlur(radius)) if radius else source
        length = _estimate_scale(np.asarray(view)[0], reference)
        if length is not None:
            estimates.append(length)
    if len(estimates) < 2:
        return BoundaryEstimate(None, "insufficient_boundary_evidence")
    if max(estimates) - min(estimates) > max(2, reference.scale * 0.2):
        return BoundaryEstimate(None, "inconsistent_scales")
    return BoundaryEstimate(int(np.median(estimates)), "scanline_consensus")


def _calibrate(row: np.ndarray) -> _Reference | None:
    gray = row.astype(np.float64).mean(axis=1)
    # A bounded prefix avoids changing the calibration when more scene is included
    # to the right. Estimate feature size from the left cap, not the crop's height.
    stop = min(64, len(row) // 3)
    body = gray[8:stop]
    baseline = float(np.median(body))
    peak = float(gray[:8].max())
    contrast = peak - baseline
    noise = float(np.median(np.abs(np.diff(body))))
    if contrast < max(8, 6 * noise):
        return None
    if np.mean(np.any(row[:stop] >= 254, axis=1)) > 0.10:
        return None
    decay = np.flatnonzero(gray[:stop] < baseline + 0.2 * contrast)
    if not len(decay):
        return None
    return _Reference(max(4, int(decay[0] * 1.5)), baseline, contrast)


def _estimate_scale(row: np.ndarray, reference: _Reference) -> int | None:
    span = reference.scale
    width = len(row)
    if width < 8 * span:
        return None
    rgb = row.astype(np.float64)
    gray = (rgb.mean(axis=1) - reference.baseline) / reference.contrast * 160 + 60
    window = max(2, round(span / 3))
    moving = np.median(sliding_window_view(gray, window), axis=1)
    rise = np.zeros(width)
    rise[window : width - window] = moving[window : width - window] - moving[: width - 2 * window]
    maxima = sliding_window_view(np.pad(rise, (window, window), constant_values=-np.inf), 2 * window + 1)
    peaks: list[int] = []
    for value in np.flatnonzero((rise > 25) & (rise >= maxima.max(axis=1))):
        x = int(value)
        if x < 3 * span or x >= width - 2 * span or (peaks and x - peaks[-1] < span):
            continue
        peaks.append(x)

    chroma = rgb.max(axis=1) - rgb.min(axis=1)
    proposals: list[tuple[int, int]] = []
    for x in peaks:
        left = gray[x - 2 * span : x - span // 2]
        right = gray[x + span : x + 3 * span]
        left_value, right_value = float(np.median(left)), float(np.median(right))
        local = gray[x - span : x + span]
        peak = float(local.max())
        cap = x - span + int(np.argmax(local)) + 1
        left_noise = 1.4826 * float(np.median(np.abs(left - left_value)))
        right_noise = float(np.std(right))

        # Empty HP to a gray limit segment or scene: require a steady left span.
        if (
            right_value - left_value > max(35, 0.4 * max(right_value, 1))
            and left_noise < 12
            and not (x == peaks[0] and any(0 < other - x < 2 * span for other in peaks))
            and peak >= right_value - 10
            and (left_value < 40 or (x != peaks[0] and x - max(p for p in peaks if p < x) > 3 * span))
        ):
            slope = np.diff(local)
            falling_cap = -slope.min() > 0.6 * slope.max()
            if peak > 1.25 * right_value and falling_cap:
                proposals.append((0, _cap_center(local, x - span)))
            elif (left_value < 40 or right_noise < 8) and slope.max() > 0.2 * (right_value - left_value):
                proposals.append((0, x))

        # Full bar, a short gray limit segment, then a second cap into a dark scene.
        following = any(
            2 * span < other - x < 8 * span
            and np.median(gray[other + span : other + 3 * span]) < min(right_value, 60)
            for other in peaks
        )
        close = any(other != x and abs(other - x) < 2 * span for other in peaks)
        initial_chroma = float(np.median(chroma[8 : min(64, width // 3)]))
        limit_chroma = float(np.median(chroma[x + span : x + 3 * span]))
        neutral_limit = initial_chroma > 0 and limit_chroma < 0.1 * initial_chroma
        clipped_cap = np.mean(np.all(row[x - span : x + span] >= 254, axis=1)) > 0.15
        if (
            x - peaks[0] < 2 * span
            and not close
            and following
            and peak > 190
            and right_value > 70
            and neutral_limit
            and not clipped_cap
        ):
            proposals.append((1, cap))

        # A bright terminal cap followed directly by a dark, steady scene.
        if (
            len(peaks) == 1
            and left_value > right_value
            and peak > 1.8 * max(left_value, 1)
            and right_noise < 8
            and right_value < 40
        ):
            fall = x - span + int(np.argmin(np.diff(local))) + 1
            proposals.append((2, fall))

        # A colored span after an internal division ends in a textured neutral
        # scene. Compare channel spread across the boundary, without a hue target.
        left_chroma = float(np.median(chroma[x - 2 * span : x - span // 2]))
        right_chroma = float(np.median(chroma[x + span // 2 : x + 3 * span]))
        if (
            x - peaks[0] > 3 * span
            and right_noise > 30
            and left_chroma > 0
            and right_chroma < 0.2 * left_chroma
            and peak > 1.25 * left_value
        ):
            changes = -np.diff(chroma[x - span : x + span])
            if changes.max() > 0.08 * left_chroma:
                proposals.append((0, x - span + int(np.argmax(changes)) + 1))
    return min(proposals)[1] if proposals else None


def _cap_center(profile: np.ndarray, start: int) -> int:
    """Interpolate a cap peak before rounding its pixel-center coordinate."""
    index = int(np.argmax(profile))
    offset = 0.0
    if 0 < index < len(profile) - 1:
        left, center, right = profile[index - 1 : index + 2]
        curvature = left - 2 * center + right
        if curvature < 0:
            offset = float(0.5 * (left - right) / curvature)
    return round(start + index + offset + 0.5)
