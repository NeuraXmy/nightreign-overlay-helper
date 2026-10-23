"""Self-down ring detector. Input is a tightly cropped uint8 RGB icon.

No game/plugin imports, persistent state, file IO, or capture dependencies.
"""

from __future__ import annotations

import cv2
import numpy as np

THRESHOLD = 0.50
_SIZE = 32


def _make_template(*, first_sector: bool = False, fill_degrees: float | None = None) -> np.ndarray:
    y, x = np.mgrid[:_SIZE, :_SIZE].astype(np.float32)
    x = (x - (_SIZE - 1) / 2) / (_SIZE / 2)
    y = (y - (_SIZE - 1) / 2) / (_SIZE / 2)
    radius = np.hypot(x, y)
    angle = np.degrees(np.arctan2(y, x))
    separator = np.minimum.reduce([np.abs((angle - center + 180) % 360 - 180) for center in (-90, 30, 150)])
    groove = (radius > 0.40) & (radius < 0.75) & (separator > 10)
    highlight = (
        (radius < 0.27)
        | ((radius > 0.89) & (radius < 0.98))
        | ((radius > 0.40) & (radius < 0.80) & (separator < 3))
    )
    template = np.zeros((_SIZE, _SIZE), np.float32)
    if first_sector:
        groove &= np.abs((angle + 30 + 180) % 360 - 180) < 46
    if fill_degrees is not None:
        groove &= (angle + 90) % 360 < fill_degrees
    template[groove] = -1
    template[highlight] = 1
    # Three pixels of search margin in the normalized input, roughly ±11 pixels
    # at 115×115. The surrounding game scene does not enter the template.
    return np.ascontiguousarray(template[3:-3, 3:-3])


_TEMPLATE = _make_template()
_FIRST_TEMPLATE = _make_template(first_sector=True)
_PROGRESS_TEMPLATES = tuple(
    (template, (template != 0).astype(np.uint8), template > 0, template < 0)
    for template in (-_make_template(fill_degrees=angle) for angle in (20, 45, 75, 110, 160, 210, 260, 310))
)


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
    dark_score = float(cv2.minMaxLoc(cv2.matchTemplate(gray, _TEMPLATE, cv2.TM_CCOEFF_NORMED))[1])
    if dark_score >= THRESHOLD:
        return dark_score
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
