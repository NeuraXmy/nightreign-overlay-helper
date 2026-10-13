from __future__ import annotations

from typing import Any

from nightreign_overlay.core.config import BoolOption, ChoiceOption, ConfigGroup, Option, RangeOption


def _periods(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(v, int) and 1 <= v <= 3600 for v in value)
    )


class DayTimerConfig(ConfigGroup):
    auto_detect = BoolOption(True)
    language = ChoiceOption("chs", ("chs", "cht", "eng", "jp"))
    hdr_processing = BoolOption(False)
    day_period_seconds = Option[list[int]]([270, 180, 210, 180], validator=_periods)
    forward_seconds = RangeOption(10, 1, 120)
    backward_seconds = RangeOption(10, 1, 120)
    score_threshold = RangeOption(80, 1, 100)
