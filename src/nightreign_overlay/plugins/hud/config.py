from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ConfigGroup


class HudConfig(ConfigGroup):
    enabled = BoolOption(True)
    hide_text = BoolOption(False)
