from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ChoiceOption, ConfigGroup, RangeOption


class CaptureConfig(ConfigGroup):
    mode = ChoiceOption("legacy", ("legacy", "foreground", "background"))
    interval_ms = RangeOption(250, 50, 2000)
    hdr_processing = BoolOption(False)
