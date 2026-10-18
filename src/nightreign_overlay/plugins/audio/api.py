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

    def is_playing(self, owner: str | None = None) -> bool:
        """Whether the shared player is currently playing audio, optionally for one owner."""
        return False


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

    def play_test(self, cue: AudioCueConfig) -> None:
        if (audio := self.ctx.services.get(AudioApi)) is not None:
            audio.play(cue.path.value, cue.volume.value, owner=f"{self.ctx.plugin_id}:test")

    def stop_test(self) -> None:
        if (audio := self.ctx.services.get(AudioApi)) is not None:
            audio.stop(f"{self.ctx.plugin_id}:test")

    def is_test_playing(self) -> bool:
        audio = self.ctx.services.get(AudioApi)
        return audio is not None and audio.is_playing(f"{self.ctx.plugin_id}:test")
