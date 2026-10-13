from __future__ import annotations

from nightreign_overlay.core.config import ConfigGroup, RangeOption


class ArtTimerConfig(ConfigGroup):
    detect_delay_ms = RangeOption(500, 0, 3000)
    # Thousandths of the normalized match score; lower is stricter.
    match_threshold = RangeOption(20, 1, 200)
