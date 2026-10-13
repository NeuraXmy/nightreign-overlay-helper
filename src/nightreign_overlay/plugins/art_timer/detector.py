"""Port of the legacy masked multi-scale template matcher for character art (ultimate) icons."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage

from nightreign_overlay.plugins.capture.api import crop_rgb, hdr_to_sdr, resize_to_height

ART_TYPES = ("duchess", "recluse", "revenant", "scholar", "executor")
#: Legacy ``art_detect_standard_size``: icons and the selection are normalized to this height.
STANDARD_SIZE = 50
_SCALES = np.linspace(0.95, 1.05, 5)


@dataclass(frozen=True)
class ArtDetectResult:
    art_type: str | None
    best_score: float
    scores: dict[str, float]


class ArtDetector:
    def __init__(self, icon_dir: Path) -> None:
        self._templates: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for art_type in ART_TYPES:
            image = cv2.imread(str(icon_dir / f"{art_type}.png"), cv2.IMREAD_UNCHANGED)
            if image is None or image.ndim != 3 or image.shape[2] != 4:
                continue
            rgba = cv2.cvtColor(resize_to_height(image, STANDARD_SIZE), cv2.COLOR_BGRA2RGBA)
            # Only the icon centre is matched; the binarized alpha ignores the transparent background.
            height, width = rgba.shape[:2]
            center = rgba[height // 4 : height * 3 // 4, width // 4 : width * 3 // 4]
            _, mask = cv2.threshold(center[:, :, 3], 127, 255, cv2.THRESH_BINARY)
            self._templates[art_type] = (np.ascontiguousarray(center[:, :, :3]), mask)

    def missing(self) -> list[str]:
        return [art_type for art_type in ART_TYPES if art_type not in self._templates]

    def detect(
        self, frame: QImage, region: QRect, threshold: float, *, hdr: bool = False
    ) -> ArtDetectResult | None:
        image = crop_rgb(frame, region)
        if image is None:
            return None
        if hdr:
            image = hdr_to_sdr(image)
        image = resize_to_height(image, STANDARD_SIZE)
        scores = {art_type: _match(image, *template) for art_type, template in self._templates.items()}
        best_type, best_score = None, 1.0
        for art_type, score in scores.items():
            if score < best_score:
                best_type, best_score = art_type, score
        return ArtDetectResult(best_type if best_score < threshold else None, best_score, scores)


def _match(image: np.ndarray, template: np.ndarray, mask: np.ndarray) -> float:
    best = float("inf")
    for scale in _SCALES:
        size = (int(template.shape[1] * scale), int(template.shape[0] * scale))
        resized = cv2.resize(template, size)
        if resized.shape[0] > image.shape[0] or resized.shape[1] > image.shape[1]:
            continue
        # The mask is ignored by TM_SQDIFF_NORMED, so the legacy code normalizes masked TM_SQDIFF by the
        # active pixel count instead; the result stays comparable to the normalized score scale.
        resized_mask = cv2.resize(mask, size)
        result = cv2.matchTemplate(image, resized, cv2.TM_SQDIFF, mask=resized_mask)
        active = max(1, np.count_nonzero(resized_mask) * resized.shape[2])
        best = min(best, float(result.min()) / (active * 255.0 * 255.0))
    return best
