"""HP marker appearance and detection parameters, in their original units."""

from __future__ import annotations

from dataclasses import dataclass

from nightreign_overlay.core.config import ColorOption, ConfigGroup, RangeOption


@dataclass(frozen=True)
class HpDetectionSettings:
    hpbar_region_aspect_ratio: int = 125
    hpbar_detection_offset: int = 3


class HpMarkerConfig(ConfigGroup):
    hpbar_low_hp_marker = RangeOption(0.4, 0.0, 1.0)
    hpbar_high_hp_marker = RangeOption(0.85, 0.0, 1.0)
    marker_color = ColorOption("#ffffff")
    marker_size = RangeOption(100, 50, 300)
    line_width = RangeOption(3, 1, 20)
    line_height = RangeOption(7, 1, 40)
    hpbar_region_aspect_ratio = RangeOption(125, 1, 300)
    hpbar_detection_offset = RangeOption(3, -20, 20)

    def snapshot(self) -> HpDetectionSettings:
        """Copy GUI configuration for the worker without passing any Qt objects."""
        return HpDetectionSettings(
            **{name: self.item(name).value for name in HpDetectionSettings.__dataclass_fields__}
        )
