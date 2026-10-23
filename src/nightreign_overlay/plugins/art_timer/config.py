from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ConfigGroup, RangeOption


class ArtTimerConfig(ConfigGroup):
    undertaker_enabled = BoolOption(True)
    undertaker_pink_percent = RangeOption(80, 1, 100)
    undertaker_duration = RangeOption(5, 1, 60)
    detect_delay_ms = RangeOption(500, 0, 3000)
    # Thousandths of the normalized match score; lower is stricter.
    match_threshold = RangeOption(20, 1, 200)
