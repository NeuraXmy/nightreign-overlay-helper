"""Legacy map parameters and their persisted, observable plugin configuration."""

from __future__ import annotations

from dataclasses import dataclass

from nightreign_overlay.core.config import ChoiceOption, ConfigGroup, Option, RangeOption


@dataclass(frozen=True)
class MapDetectionSettings:
    """Immutable settings snapshot passed to the worker, with legacy config.yaml defaults."""

    poi_algorithm: str = "cnn"
    earth_shifting_algorithm: str = "ncc"
    fixed_map_overlay_draw_size: tuple[int, int] | None = None
    map_overlay_draw_size_ratio: float | None = 1.0
    full_map_hough_circle_thres: tuple[int, ...] = (150, 200, 250)
    full_map_error_threshold: float = 20
    earth_shifting_ncc_threshold: float = 0.2
    earth_shifting_error_threshold: float = 50
    subicon_template_match_threshold: float = 0.06
    poi_match_sample_ratio_w_nightlord: float = 1.0
    poi_match_sample_ratio_wo_nightlord: float = 1.0


class MapDetectConfig(ConfigGroup):
    """Keep the original advanced parameters available in settings.yaml without changing their scale."""

    poi_algorithm = ChoiceOption("cnn", ("template", "cnn"))
    earth_shifting_algorithm = ChoiceOption("ncc", ("ncc", "template"))
    return_topk = RangeOption(3, 1, 10)
    map_pattern_match_interval = RangeOption(2100, 1, 86400)
    fixed_map_overlay_draw_size = Option(
        None,
        validator=lambda v: (
            v is None
            or (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and x > 0 for x in v))
        ),
    )
    map_overlay_draw_size_ratio = Option(
        1.0,
        validator=lambda v: v is None or (isinstance(v, int | float) and not isinstance(v, bool) and v > 0),
    )
    full_map_hough_circle_thres = Option(
        [150, 200, 250],
        validator=lambda v: (
            isinstance(v, list) and len(v) > 0 and all(isinstance(x, int) and x > 0 for x in v)
        ),
    )
    full_map_error_threshold = RangeOption(20.0, 0.0, 1000.0)
    earth_shifting_ncc_threshold = RangeOption(0.2, -1.0, 1.0)
    earth_shifting_error_threshold = RangeOption(50.0, 0.0, 1000.0)
    subicon_template_match_threshold = RangeOption(0.06, 0.0, 1.0)
    poi_match_sample_ratio_w_nightlord = RangeOption(1.0, 0.0, 1.0)
    poi_match_sample_ratio_wo_nightlord = RangeOption(1.0, 0.0, 1.0)

    def snapshot(self) -> MapDetectionSettings:
        """Copy Qt-owned config into plain values before crossing the thread boundary."""
        values = {name: self.item(name).value for name in MapDetectionSettings.__dataclass_fields__}
        values["full_map_hough_circle_thres"] = tuple(values["full_map_hough_circle_thres"])
        if values["fixed_map_overlay_draw_size"] is not None:
            values["fixed_map_overlay_draw_size"] = tuple(values["fixed_map_overlay_draw_size"])
        return MapDetectionSettings(**values)
