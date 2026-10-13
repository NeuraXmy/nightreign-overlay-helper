"""HP marker appearance and legacy detection parameters, in their original units."""

from __future__ import annotations

from dataclasses import dataclass

from nightreign_overlay.core.config import BoolOption, ColorOption, ConfigGroup, RangeOption


@dataclass(frozen=True)
class HpDetectionSettings:
    hpbar_region_aspect_ratio: int = 125
    hpbar_detect_std_height: int = 15
    hpbar_border_v_peak_start: int = 30
    hpbar_border_v_peak_lower: int = 100
    hpbar_border_v_peak_threshold: int = 75
    hpbar_border_v_peak_interval: int = 30
    hpbar_recent_length_count: int = 10


class HpMarkerConfig(ConfigGroup):
    # Retained for old settings compatibility; the old detector never reads this switch.
    keep_last_valid = BoolOption(False)
    hpbar_low_hp_marker = RangeOption(0.4, 0.0, 1.0)
    hpbar_high_hp_marker = RangeOption(0.85, 0.0, 1.0)
    marker_color = ColorOption("#ffffff")
    line_width = RangeOption(3, 1, 20)
    line_height = RangeOption(7, 1, 40)
    hpbar_region_aspect_ratio = RangeOption(125, 1, 300)
    hpbar_detect_std_height = RangeOption(15, 1, 100)
    hpbar_border_v_peak_start = RangeOption(30, 0, 300)
    hpbar_border_v_peak_lower = RangeOption(100, 0, 255)
    hpbar_border_v_peak_threshold = RangeOption(75, 0, 255)
    hpbar_border_v_peak_interval = RangeOption(30, 2, 300)
    hpbar_recent_length_count = RangeOption(10, 3, 100)

    def snapshot(self) -> HpDetectionSettings:
        """Copy GUI configuration for the worker without passing any Qt objects."""
        return HpDetectionSettings(
            **{name: self.item(name).value for name in HpDetectionSettings.__dataclass_fields__}
        )
