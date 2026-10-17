"""Single-player contract shared by notification producers and settings previews."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nightreign_overlay.core.audio import AudioCueConfig, AudioTimeline

if TYPE_CHECKING:
    from nightreign_overlay.plugin.context import PluginContext


class AudioApi:
    def play(self, path: str, volume: int = 100, *, owner: str = "") -> bool:
        """Replace current playback; return False for unavailable audio."""
        raise NotImplementedError

    def stop(self, owner: str | None = None) -> None:
        """Stop playback, optionally only if it belongs to the given feature."""
        raise NotImplementedError


class AudioNotifications:
    """Feature-owned cue settings and history; playback always uses the shared service."""

    def __init__(self, ctx: PluginContext, keys: tuple[str, ...]) -> None:
        self.ctx = ctx
        self.cues = {key: ctx.config(AudioCueConfig, f"audio.{key}") for key in keys}
        self.timeline = AudioTimeline(self.play)

    def play(self, cue: AudioCueConfig) -> None:
        if (audio := self.ctx.services.get(AudioApi)) is not None:
            audio.play(cue.path.value, cue.volume.value, owner=self.ctx.plugin_id)

    def reset(self) -> None:
        self.timeline.reset()
        if (audio := self.ctx.services.get(AudioApi)) is not None:
            audio.stop(self.ctx.plugin_id)

    def update(self, elapsed: float, deadlines: dict[str, float]) -> None:
        self.timeline.update(elapsed, [(key, value, self.cues[key]) for key, value in deadlines.items()])
