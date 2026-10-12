from __future__ import annotations

from nightreign_overlay.core.config import ChoiceOption, ConfigGroup, RangeOption


class HudConfig(ConfigGroup):
    direction = ChoiceOption("vertical", ("vertical", "horizontal"))
    spacing = RangeOption(8, 0, 40)
