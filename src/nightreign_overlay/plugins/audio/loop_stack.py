"""Owner-addressable stack for mutually exclusive looping cues."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LoopAudioEntry:
    owner: str
    path: str
    volume: int
    fade_in: float
    fade_out: float = 0.0
    position_ms: int = 0


class LoopAudioStack:
    """Keep one loop per owner; pushing an owner moves it to the audible top."""

    def __init__(self) -> None:
        self._entries: list[LoopAudioEntry] = []

    @property
    def top(self) -> LoopAudioEntry | None:
        return self._entries[-1] if self._entries else None

    def get(self, owner: str) -> LoopAudioEntry | None:
        return next((entry for entry in self._entries if entry.owner == owner), None)

    def put(self, entry: LoopAudioEntry) -> None:
        self.remove(entry.owner)
        self._entries.append(entry)

    def set_fade_out(self, owner: str, seconds: float) -> None:
        if (entry := self.get(owner)) is not None:
            entry.fade_out = max(0.0, seconds)

    def remove(self, owner: str) -> LoopAudioEntry | None:
        entry = self.get(owner)
        if entry is not None:
            self._entries.remove(entry)
        return entry

    def clear(self) -> None:
        self._entries.clear()
