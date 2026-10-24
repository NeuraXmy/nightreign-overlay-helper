"""Configuration for the status-meter attack buff timer."""

from __future__ import annotations

from nightreign_overlay.core.config import ConfigGroup, RangeOption


class DebuffTimerConfig(ConfigGroup):
    # The first checkpoint starts slightly early to compensate for detection latency.
    first_check_advance = RangeOption(0.2, 0.0, 20.0)
