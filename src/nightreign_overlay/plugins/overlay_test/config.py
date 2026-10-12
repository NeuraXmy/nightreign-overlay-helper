from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ColorOption, ConfigGroup, RangeOption


class OverlayTestConfig(ConfigGroup):
    cycle_seconds = RangeOption(30, 5, 300)
    accent_color = ColorOption("#c8a35a")
    show_background = BoolOption(True)
