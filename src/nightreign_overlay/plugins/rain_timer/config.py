from __future__ import annotations

from typing import Any

from nightreign_overlay.core.config import BoolOption, ConfigGroup, Option, RangeOption


def _hls(value: Any) -> bool:
    """A calibrated HLS colour, or ``None`` for the legacy built-in colour range."""
    return value is None or (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255 for v in value)
    )


class RainTimerConfig(ConfigGroup):
    auto_detect = BoolOption(True)
    # Calibrated colours; the normal and HDR image modes keep separate values like the legacy app.
    not_in_rain_hls = Option[list[int] | None](None, validator=_hls)
    in_rain_hls = Option[list[int] | None](None, validator=_hls)
    not_in_rain_hls_hdr = Option[list[int] | None](None, validator=_hls)
    in_rain_hls_hdr = Option[list[int] | None](None, validator=_hls)
    duration_seconds = RangeOption(110, 1, 600)
    h_tolerance = RangeOption(5, 0, 90)
    l_tolerance = RangeOption(30, 0, 255)
    s_tolerance = RangeOption(30, 0, 255)
    min_area_percent = RangeOption(10, 0, 100)
    max_area_percent = RangeOption(50, 0, 100)
