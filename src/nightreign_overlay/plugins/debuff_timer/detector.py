"""Presence detection for an abnormal-status icon and its aligned buildup meter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

_NORMALIZED_SIZE = (225, 160)
_DEFAULT_ICONS = Path(__file__).with_name("icons")


@dataclass(frozen=True)
class Detection:
    present: bool
    icon_score: float
    bar_score: float
    # Location in the supplied ROI, not the full game image.
    icon_rect: tuple[int, int, int, int] | None = None


class DebuffDetector:
    def __init__(self, icons: Path = _DEFAULT_ICONS) -> None:
        references = []
        for path in sorted(icons.glob("*.png")):
            data = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
            if data is None:
                raise ValueError(f"Invalid icon: {path}")
            references.append(cv2.cvtColor(data[..., :3], cv2.COLOR_BGR2GRAY))
        if not references:
            raise ValueError("No condition icon templates")
        self.templates = []
        self._geometry = []
        # Try the expected icon size across all types before less common scales.
        for size in (22, 24, 20, 26, 28):
            # References exclude three pixels on each side of the original
            # 43px icon. Preserve the outer geometry for bar alignment.
            inner_size = round(size * 37 / 43)
            inset = (size - inner_size) // 2
            for gray in references:
                self.templates.append(
                    cv2.resize(gray, (inner_size, inner_size), interpolation=cv2.INTER_AREA)
                )
                self._geometry.append((size, inset))

    @staticmethod
    def _bar_score(gray: np.ndarray, x: int, y: int, size: int) -> float:
        # A bar is a thin horizontal strip aligned with the icon center. It
        # may be brighter OR darker than the scene, and nearly empty OR full.
        x0 = x + size + 5
        x1 = min(gray.shape[1], x0 + 85)
        if x1 - x0 < 60:
            return 0.0
        cy = y + size // 2
        best = 0.0
        for yy in range(max(5, cy - 4), min(gray.shape[0] - 5, cy + 5)):
            center = gray[yy, x0:x1]
            surround = (gray[yy - 5, x0:x1] + gray[yy + 5, x0:x1]) * 0.5
            difference = center - surround
            # Scale the contrast requirement with the local luminance range.
            band = gray[max(0, yy - 8) : yy + 9, x0:x1]
            low, high = np.percentile(band, (10, 90))
            threshold = max(1.0, float(high - low) * 0.025)
            coverage = max(float(np.mean(difference > threshold)), float(np.mean(difference < -threshold)))
            strength = min(1.0, float(np.mean(np.abs(difference))) / (threshold * 2))
            best = max(best, coverage * strength)
        return best

    def detect(self, rgb: np.ndarray) -> Detection:
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 32:
            raise ValueError("Expected a uint8 RGB meter region at least 32 pixels wide/high")
        small = cv2.resize(rgb, _NORMALIZED_SIZE, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        floating = gray.astype(np.float32)
        best_bar = 0.0
        best_icon = 0.0
        for template, (size, inset) in zip(self.templates, self._geometry, strict=True):
            scores = cv2.matchTemplate(gray[:, :135], template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            best_icon = max(best_icon, score)
            if score >= 0.80:
                # Match only the cropped icon, then restore its outer bounds
                # to locate the bar. A valid icon + bar suffices; avoid testing
                # every remaining type/scale when presence is already certain.
                inner_size = template.shape[0]
                interior = gray[y + 2 : y + inner_size - 2, x + 2 : x + inner_size - 2]
                detail = float(cv2.matchTemplate(interior, template[2:-2, 2:-2], cv2.TM_CCOEFF_NORMED)[0, 0])
                if detail < 0.70:
                    continue
                x -= inset
                y -= inset
                bar = self._bar_score(floating, x, y, size)
                best_bar = max(best_bar, bar)
                if bar < 0.42:
                    continue
                sx, sy = rgb.shape[1] / 225, rgb.shape[0] / 160
                return Detection(
                    True, score, bar, (round(x * sx), round(y * sy), round(size * sx), round(size * sy))
                )
        return Detection(False, best_icon, best_bar)
