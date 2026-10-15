"""HP marker appearance and detection parameters, in their original units."""

from __future__ import annotations

from dataclasses import dataclass

from nightreign_overlay.core.config import ChoiceOption, ColorOption, ConfigGroup, RangeOption


@dataclass(frozen=True)
class HpDetectionSettings:
    detection_algorithm: str = "structural"
    hpbar_region_aspect_ratio: int = 125
    hpbar_detect_std_height: int = 15
    hpbar_border_v_peak_start: int = 30
    hpbar_border_v_peak_lower: int = 100
    hpbar_border_v_peak_threshold: int = 75
    hpbar_border_v_peak_interval: int = 30
    hpbar_recent_length_count: int = 10


class HpMarkerConfig(ConfigGroup):
    hpbar_low_hp_marker = RangeOption(0.4, 0.0, 1.0)
    detection_algorithm = ChoiceOption("structural", ("legacy", "structural"))
    hpbar_high_hp_marker = RangeOption(0.85, 0.0, 1.0)
    marker_color = ColorOption("#ffffff")
    marker_size = RangeOption(100, 50, 300)
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
