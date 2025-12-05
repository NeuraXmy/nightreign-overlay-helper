import yaml
import os
from dataclasses import dataclass

from .common import load_yaml

CONFIG_PATH = "config.yaml"

_config: dict = {}
_config_mtime = None

@dataclass
class Config:
    day_period_seconds: list[int]
    deadly_nightrain_seconds: int

    update_interval: float
    detect_intervals: dict[str, float]

    foward_day_seconds: int
    back_day_seconds: int

    day_progress_css: str
    day_text_css: str
    in_rain_progress_css: str
    in_rain_text_css: str
    art_progress_css: str
    art_text_css: str

    time_scale: float

    template_standard_height: int
    mask_lower_white: list[int]
    mask_upper_white: list[int]
    scale_range: list[float]
    dayx_score_threshold: float
    dayx_detect_langs: dict[str, str]

    lower_hls_not_in_rain: list[int]
    upper_hls_not_in_rain: list[int]
    lower_hls_in_rain: list[int]
    upper_hls_in_rain: list[int]
    lower_hls_not_in_rain_hdr: list[int]
    upper_hls_not_in_rain_hdr: list[int]
    lower_hls_in_rain_hdr: list[int]
    upper_hls_in_rain_hdr: list[int]
    h_tolerance: int
    l_tolerance: int
    s_tolerance: int
    hp_color_min_area_ratio: float
    hp_color_max_area_ratio: float

    fixed_map_overlay_draw_size: list[int] | None
    map_overlay_draw_size_ratio: float | None
    full_map_hough_circle_thres: list[int]
    full_map_error_threshold: float
    earth_shifting_error_threshold: float
    map_pattern_match_interval: float

    hpbar_region_aspect_ratio: float
    hpbar_detect_std_height: int
    hpbar_border_v_peak_start: int
    hpbar_border_v_peak_lower: int
    hpbar_border_v_peak_threshold: int
    hpbar_border_v_peak_interval: int
    hpbar_recent_length_count: int
    hpbar_low_hp_marker: float
    hpbar_high_hp_marker: float

    art_detect_standard_size: int
    art_detect_match_scales: tuple[float, float, int]
    art_detect_threshold: float
    art_detect_delay_seconds: float
    art_info: dict[str, dict[str, float]]

    bug_report_email: str

    @staticmethod
    def get() -> 'Config':
        global _config, _config_mtime
        mtime = os.path.getmtime(CONFIG_PATH)
        if mtime != _config_mtime:
            _config = load_yaml(CONFIG_PATH)
            _config_mtime = mtime
        return Config(**_config)