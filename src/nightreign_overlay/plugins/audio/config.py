"""Shared configuration for owner-controlled looping audio cues."""

from __future__ import annotations

from nightreign_overlay.core.config import BoolOption, ConfigGroup, Option, RangeOption


class LoopAudioConfig(ConfigGroup):
    enabled = BoolOption(False)
    path = Option("", validator=lambda value: isinstance(value, str))
    volume = RangeOption(100, 0, 100)
    fade_in = RangeOption(0.0, 0.0, 60.0)
    fade_out = RangeOption(0.0, 0.0, 60.0)
