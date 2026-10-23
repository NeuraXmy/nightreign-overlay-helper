"""Bounded-cost structural classifier for the two teammate HUD rows."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .ring_geometry import make_ring_template

_DARK = make_ring_template()
_PURPLE = -_DARK
_FIRST = -make_ring_template(first_sector=True)
_WIDTH = 240


@dataclass(frozen=True)
class Teammate:
    present: bool
    down: bool
    stages: int
    confidence: float
    center: tuple[float, float]


def _has_hp_strip(rgb: np.ndarray, nominal_y: float) -> bool:
    """Require a thin warm strip starting at the HUD's fixed HP origin."""
    channels = rgb.astype(np.float32)
    warm = channels[..., 0] - channels[..., 2]
    height = rgb.shape[0]
    for y in range(max(5, round(nominal_y - 20)), min(height - 5, round(nominal_y + 4))):
        middle = warm[y, 74:216]
        contrast = middle - (warm[y - 5, 74:216] + warm[y + 5, 74:216]) / 2
        filled = (middle > 1.5) & (contrast > 1.5)
        # A menu item or scenery patch can have a long warm edge elsewhere.
        # Real HP starts beside the portrait, including partially depleted HP.
        if filled[:16].mean() < 0.6:
            continue
        edges = np.diff(np.r_[False, filled, False].astype(np.int8))
        lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        if lengths.max(initial=0) >= 17:
            return True
    return False


def _detect_row(rgb: np.ndarray, row_index: int) -> Teammate:
    height = rgb.shape[0]
    nominal_y = height * (0.25 if row_index == 0 else 0.74)
    nominal_x = _WIDTH * 0.165
    best = [0.0, 0.0, 0.0]
    centers = [(nominal_x, nominal_y)] * 3
    # Fixed work at every capture resolution. Each 32px crop searches a 7x7
    # center window and five physical ring sizes, rather than filtering the
    # entire capture once per radius. No image-derived reference is used.
    for side in (36, 40, 44, 48, 52):
        x0, y0 = round(nominal_x - side / 2), round(nominal_y - side / 2)
        if y0 < 0 or y0 + side > height:
            continue
        small = cv2.resize(rgb[y0 : y0 + side, x0 : x0 + side], (32, 32), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
        channels = small.astype(np.float32)
        purple = channels[..., 2] - channels[..., 1]
        for index, (source, template) in enumerate(((gray, _DARK), (purple, _PURPLE), (purple, _FIRST))):
            _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED))
            if score > best[index]:
                best[index] = score
                centers[index] = (x0 + (x + 12.5) * side / 32, y0 + (y + 12.5) * side / 32)
    # Normalize each branch against its threshold. Dark grooves also cover
    # the gold rescue ring; purple structure distinguishes a fully filled
    # three-down ring from one/two-down without depending on absolute light.
    ratios = np.asarray(best) / (0.46, 0.53, 0.51)
    branch = int(ratios.argmax())
    down = bool(ratios[branch] >= 1)
    present = down or _has_hp_strip(rgb, nominal_y)
    return Teammate(
        present,
        down,
        (3 if best[1] >= 0.72 else 1) if down else 0,
        best[branch] if present else 0.0,
        centers[branch] if present else (0.0, 0.0),
    )


def detect_rgb(rgb: np.ndarray, *, teammate_count: int = 2) -> tuple[Teammate, Teammate]:
    if teammate_count not in (1, 2):
        raise ValueError("teammate_count must be 1 or 2")
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 8:
        raise ValueError("Expected a uint8 RGB HUD crop at least 8 pixels wide and tall")
    original_width = rgb.shape[1]
    height = max(8, round(rgb.shape[0] * _WIDTH / original_width))
    rgb = cv2.resize(rgb, (_WIDTH, height), interpolation=cv2.INTER_AREA)
    absent = Teammate(False, False, 0, 0.0, (0.0, 0.0))
    # Faded/hidden HUD has too little usable contrast to claim a teammate.
    # Percentiles ignore isolated JPEG noise and compensate for a gray lift.
    if float(np.percentile(rgb, 99) - np.percentile(rgb, 1)) < 22:
        return absent, absent
    upper = _detect_row(rgb, 0)
    lower = _detect_row(rgb, 1) if teammate_count == 2 else absent
    scale = original_width / _WIDTH
    if scale == 1:
        return upper, lower
    return tuple(
        Teammate(t.present, t.down, t.stages, t.confidence, (t.center[0] * scale, t.center[1] * scale))
        for t in (upper, lower)
    )
