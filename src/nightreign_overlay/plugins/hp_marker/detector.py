"""Material and structure based HP boundary detection."""

from __future__ import annotations

import numpy as np

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.material import MaterialModel
from nightreign_overlay.plugins.hp_marker.tracking import StructuralHpDetector


class HpDetector:
    """Dispatch the single supported structural detector."""

    def __init__(self, *, material_model: MaterialModel | None = None) -> None:
        self._structural = StructuralHpDetector(material_model)

    def detect(
        self,
        image: np.ndarray,
        config: HpDetectionSettings,
        *,
        scanline_y: int | None = None,
        bar_height: int | None = None,
    ) -> int | None:
        return self._structural.detect(image, scanline_y=scanline_y, bar_height=bar_height)
