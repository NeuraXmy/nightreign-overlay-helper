from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ConfigGroup, RangeOption


class CaptureConfig(ConfigGroup):
    interval_ms = RangeOption(250, 50, 2000)
    only_when_game_foreground = BoolOption(True)
