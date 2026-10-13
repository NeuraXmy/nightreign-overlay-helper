"""Public circle-timer state for optional consumers such as map recognition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Phase(IntEnum):
    FIRST_CIRCLE_STABLE = 0
    FIRST_CIRCLE_SHRINK = 1
    SECOND_CIRCLE_STABLE = 2
    SECOND_CIRCLE_SHRINK = 3
    NIGHT_BOSS = 4


@dataclass(frozen=True)
class DayPhaseChanged:
    day: int | None
    phase: Phase | None


class DayTimerApi:
    def day(self) -> int | None:
        raise NotImplementedError

    def phase(self) -> Phase | None:
        raise NotImplementedError


def format_period(seconds: int) -> str:
    return f"{max(seconds, 0) // 60}:{max(seconds, 0) % 60:02d}"
