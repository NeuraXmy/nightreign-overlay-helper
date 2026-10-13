"""Input binding value objects shared without importing plugin implementation modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InputDevice(StrEnum):
    KEYBOARD = "keyboard"
    MOUSE = "mousebutton"
    JOYSTICK = "joystick"


@dataclass(frozen=True)
class HotkeyBinding:
    """One input-device combination; ``None`` means the action is disabled."""

    device: InputDevice | None
    keys: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.device is not None and bool(self.keys)
