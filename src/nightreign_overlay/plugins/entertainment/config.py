"""Configuration for teammate down-state playback."""

from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ChoiceOption, ConfigGroup, RangeOption


class EntertainmentConfig(ConfigGroup):
    detect_enabled = BoolOption(False)
    self_down_stop = BoolOption(True)
    three_player_only = BoolOption(False)
    start_condition = ChoiceOption("all_down", ("all_down", "all_three"))
    stop_condition = ChoiceOption("all_up", ("all_up", "any_up"))
    stable_detections = RangeOption(3, 1, 10)
