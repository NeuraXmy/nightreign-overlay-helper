"""Bundled voice resources, resolved from the installed package rather than user settings."""

from dataclasses import dataclass
from pathlib import Path

SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"


@dataclass(frozen=True)
class BundledCue:
    filename: str
    seconds: float = 0.0

    @property
    def path(self) -> Path:
        return SOUNDS_DIR / self.filename


BUNDLED_CUES = {
    ("day_timer", "day1"): BundledCue("day1.mp3"),
    ("day_timer", "day2"): BundledCue("day2.mp3"),
    ("day_timer", "day3"): BundledCue("day3.mp3"),
    ("day_timer", "first_circle"): BundledCue("first_circle.mp3", 30.0),
    ("day_timer", "second_circle"): BundledCue("second_circle.mp3", 30.0),
    ("rain_timer", "start"): BundledCue("rain_start.mp3"),
    ("rain_timer", "warning"): BundledCue("rain_warning.mp3", 30.0),
    ("rain_timer", "end"): BundledCue("rain_end.mp3"),
    ("art_timer", "start"): BundledCue("art_start.mp3"),
    ("art_timer", "end"): BundledCue("art_end.mp3", 3.0),
}

# Looping cues use an empty persisted path so installations remain portable. Feature
# plugins resolve these filenames relative to the installed audio plugin at runtime.
BUNDLED_LOOP_AUDIO = {
    ("art_timer", "executor"): "animals.mp3",
    ("entertainment", "down"): "rainlove.wav",
}


def bundled_loop_path(plugin_id: str, key: str) -> Path:
    return SOUNDS_DIR / BUNDLED_LOOP_AUDIO[(plugin_id, key)]
