"""Self-down ring detector. Input is a tightly cropped uint8 RGB icon.

No game/plugin imports, persistent state, file IO, or capture dependencies.
"""

from __future__ import annotations

import cv2
import numpy as np

from .ring_geometry import make_ring_template as _make_template

THRESHOLD = 0.50
_SIZE = 32


_TEMPLATE = _make_template()
_FIRST_TEMPLATE = _make_template(first_sector=True)
_PROGRESS_TEMPLATES = tuple(
    (template, (template != 0).astype(np.uint8), template > 0, template < 0)
    for template in (-_make_template(fill_degrees=angle) for angle in (20, 45, 75, 110, 160, 210, 260, 310))
)


def _rim_geometry() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Radial unit vectors for the icon boundary and a small center search."""
    y, x = np.mgrid[:_SIZE, :_SIZE].astype(np.float32)
    centers = np.array(
        [(cx, cy) for cy in (14.5, 15.5, 16.5, 17.5) for cx in (14.5, 15.5, 16.5, 17.5)], np.float32
    )
    dx, dy = x - centers[:, 0, None, None], y - centers[:, 1, None, None]
    radius = np.hypot(dx, dy)
    boundary = (radius > 11) & (radius < 16)
    return dx / np.maximum(radius, 1) * boundary, dy / np.maximum(radius, 1) * boundary, boundary


_RADIAL_X, _RADIAL_Y, _BOUNDARY = _rim_geometry()


def _rim_coherence(gray: np.ndarray) -> float:
    """Measure whether boundary gradients point toward a common ring center.

    Squared projections accept both bright and dark rims. Dividing by local
    gradient energy cancels linear brightness/contrast changes. A small blue
    streak can match a filled wedge but lacks this circular boundary.
    """
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    radial = ((gx * _RADIAL_X + gy * _RADIAL_Y) ** 2).sum(axis=(1, 2))
    energy = ((gx * gx + gy * gy) * _BOUNDARY).sum(axis=(1, 2))
    return float((radial / np.maximum(energy, 1)).max())


def score_gray(gray: np.ndarray) -> float:
    """Score a nonempty grayscale crop; shared by offline sample evaluation.

    Normalized correlation compensates for linear brightness/contrast changes.
    This branch handles the mostly empty dark grooves of a low-progress ring.
    """
    small = cv2.resize(gray, (_SIZE, _SIZE), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    matches = cv2.matchTemplate(small, _TEMPLATE, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(matches)[1])


def score_rgb(rgb: np.ndarray) -> float:
    """Return structural similarity; larger values indicate a self-down ring."""
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected a uint8 RGB image with three channels")
    if min(rgb.shape[:2]) < 8:
        raise ValueError("Expected an icon at least 8×8 pixels")
    small = cv2.resize(rgb, (_SIZE, _SIZE), interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    rim = _rim_coherence(gray)
    if rim < 0.60:
        return 0.0
    dark_score = float(cv2.minMaxLoc(cv2.matchTemplate(gray, _TEMPLATE, cv2.TM_CCOEFF_NORMED))[1])
    if dark_score >= THRESHOLD:
        return dark_score
    # Gold rescue progress can flatten/recolor the grooves. Relax their
    # correlation only when a strongly circular boundary confirms the ring.
    if rim >= 0.85 and dark_score >= 0.38:
        return THRESHOLD
    # Filled rings reverse the luminance contrast. Instead of accepting any
    # reversed gray pattern, require purple chroma in the annular sectors.
    channels = small.astype(np.float32)
    purple = channels[..., 2] - channels[..., 1]
    if float(purple.max() - purple.min()) < 8:
        return dark_score
    purple_score = float(cv2.minMaxLoc(cv2.matchTemplate(purple, -_TEMPLATE, cv2.TM_CCOEFF_NORMED))[1])
    if purple_score < THRESHOLD:
        # One/two-down rings leave other wedges dark. Match the first wedge
        # separately, retaining the center/rim/separator exclusion structure.
        purple_score = max(
            purple_score,
            float(cv2.minMaxLoc(cv2.matchTemplate(purple, -_FIRST_TEMPLATE, cv2.TM_CCOEFF_NORMED))[1]),
        )
    # Strong highlight clipping can flatten blue chroma inside the ring.
    # In that case retain the reversed luminance structure, but require
    # appreciable violet/blue chroma so gray scenery cannot use this branch.
    filled_score = 0.0
    if purple_score < THRESHOLD and float(purple.mean()) >= 12:
        filled_score = float(cv2.minMaxLoc(cv2.matchTemplate(gray, -_TEMPLATE, cv2.TM_CCOEFF_NORMED))[1])
    score = max(dark_score, purple_score, filled_score)
    if score >= THRESHOLD:
        return score
    # Match only the filled prefix and structural exclusions; unfilled wedges
    # do not participate in the normalized correlation.
    partial = purple
    for template, mask, positive_mask, negative_mask in _PROGRESS_TEMPLATES:
        matches = np.nan_to_num(
            cv2.matchTemplate(partial, template, cv2.TM_CCOEFF_NORMED, mask=mask),
            nan=-1,
            posinf=-1,
            neginf=-1,
        )
        _, correlation, _, (x, y) = cv2.minMaxLoc(matches)
        patch = partial[y : y + template.shape[0], x : x + template.shape[1]]
        contrast = float(patch[positive_mask].mean() - patch[negative_mask].mean())
        if contrast >= 8 and (correlation >= 0.80 or (dark_score >= 0.40 and correlation >= 0.50)):
            score = max(score, correlation)
        if score >= THRESHOLD:
            break
        # At clipped highlights chroma can flatten while the wedge remains
        # bright. Require local purple/red chroma at the same matched position.
        matches = np.nan_to_num(
            cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED, mask=mask), nan=-1, posinf=-1, neginf=-1
        )
        _, correlation, _, (x, y) = cv2.minMaxLoc(matches)
        color_patch = channels[y : y + template.shape[0], x : x + template.shape[1]]
        positive = color_patch[positive_mask]
        if (
            correlation >= 0.75
            and float((positive[:, 0] - positive[:, 1]).mean()) >= 8
            and float((positive[:, 2] - positive[:, 1]).mean()) >= 12
        ):
            score = max(score, correlation)
            break
    return score


def is_down(rgb: np.ndarray) -> bool:
    """Classify down/upright only, without distinguishing ring stages."""
    return score_rgb(rgb) >= THRESHOLD
