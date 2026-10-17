"""Reusable cue configuration and elapsed-time scheduling, independent of playback backends."""

from __future__ import annotations

import math
from collections.abc import Callable

from nightreign_overlay.core.config import ConfigGroup, Option, RangeOption


class _SecondsOption(RangeOption[float]):
    def normalize(self, raw: object) -> float:
        value = super().normalize(raw)
        if not math.isfinite(value):
            raise ValueError("audio offset must be finite")
        return value


class AudioCueConfig(ConfigGroup):
    """One optional local audio cue; an empty path disables it."""

    path = Option("", validator=lambda value: isinstance(value, str))
    volume = RangeOption(100, 0, 100)
    seconds = _SecondsOption(0.0, 0.0, 3600.0)


class AudioTimeline:
    """Play each cue once per run, including when the clock jumps past its deadline.

    Deadlines are recomputed from current settings by the caller. Rewinding never repeats a cue;
    restarting clears the history. Negative deadlines play at start.
    """

    def __init__(self, play: Callable[[AudioCueConfig], None]) -> None:
        self._play = play
        self._fired: set[str] = set()

    def reset(self) -> None:
        self._fired.clear()

    def fire(self, key: str, cue: AudioCueConfig) -> None:
        if key not in self._fired:
            self._fired.add(key)
            self._play(cue)

    def update(self, elapsed: float, cues: list[tuple[str, float, AudioCueConfig]]) -> None:
        for key, deadline, cue in sorted(cues, key=lambda entry: entry[1]):
            if math.isfinite(deadline) and elapsed >= max(0.0, deadline):
                self.fire(key, cue)
