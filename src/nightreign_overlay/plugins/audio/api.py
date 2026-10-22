"""Single-player contract shared by notification producers and settings previews."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nightreign_overlay.core.audio import AudioCueConfig, AudioTimeline
from nightreign_overlay.plugins.audio.defaults import BUNDLED_CUES

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

    def play_loop(self, path: str, volume: int = 100, fade_in: float = 0, *, owner: str = "") -> bool:
        raise NotImplementedError

    def stop_loop(self, owner: str, fade_out: float = 0) -> None:
        raise NotImplementedError

    def set_loop_fade_out(self, owner: str, seconds: float) -> None:
        raise NotImplementedError

    def is_loop_playing(self, owner: str) -> bool:
        raise NotImplementedError


class AudioNotifications:
    """Feature-owned cue settings and history; playback always uses the shared service."""

    def __init__(self, ctx: PluginContext, keys: tuple[str, ...]) -> None:
        self.ctx = ctx
        self.cues: dict[str, AudioCueConfig] = {}
        self._playing_cue: AudioCueConfig | None = None
        self._testing_cue: AudioCueConfig | None = None
        for key in keys:
            preset = BUNDLED_CUES.get((ctx.plugin_id, key))
            config = AudioCueConfig.with_default_seconds(preset.seconds) if preset else AudioCueConfig
            cue = ctx.config(config, f"audio.{key}")
            self.cues[key] = cue
            cue.enabled.valueChanged.connect(partial(self._enabled_changed, cue))
        self.timeline = AudioTimeline(self.play)

    def default_path(self, cue: AudioCueConfig) -> str:
        for key, candidate in self.cues.items():
            if candidate is cue and (preset := BUNDLED_CUES.get((self.ctx.plugin_id, key))):
                return str(preset.path)
        return ""

    def path_for(self, cue: AudioCueConfig) -> str:
        # Never persist the installation path: moving the ZIP must keep defaults working.
        return cue.path.value or self.default_path(cue)

    def _enabled_changed(self, cue: AudioCueConfig, enabled: bool) -> None:
        if enabled:
            return
        if cue is self._testing_cue:
            self.stop_test()
        if cue is self._playing_cue:
            if (audio := self.ctx.services.get(AudioApi)) is not None:
                audio.stop(self.ctx.plugin_id)
            self._playing_cue = None

    def play(self, cue: AudioCueConfig) -> None:
        if (
            cue.enabled.value
            and (audio := self.ctx.services.get(AudioApi)) is not None
            and audio.play(self.path_for(cue), cue.volume.value, owner=self.ctx.plugin_id)
        ):
            self._playing_cue = cue

    def reset(self) -> None:
        self.timeline.reset()
        if (audio := self.ctx.services.get(AudioApi)) is not None:
            audio.stop(self.ctx.plugin_id)
        self._playing_cue = None

    def update(self, elapsed: float, deadlines: dict[str, float]) -> None:
        self.timeline.update(elapsed, [(key, value, self.cues[key]) for key, value in deadlines.items()])

    def play_test(self, cue: AudioCueConfig) -> None:
        if (
            cue.enabled.value
            and (audio := self.ctx.services.get(AudioApi)) is not None
            and audio.play(self.path_for(cue), cue.volume.value, owner=f"{self.ctx.plugin_id}:test")
        ):
            self._testing_cue = cue

    def stop_test(self) -> None:
        if (audio := self.ctx.services.get(AudioApi)) is not None:
            audio.stop(f"{self.ctx.plugin_id}:test")
        self._testing_cue = None

    def is_test_playing(self, cue: AudioCueConfig | None = None) -> bool:
        audio = self.ctx.services.get(AudioApi)
        return (
            audio is not None
            and (cue is None or cue is self._testing_cue)
            and audio.is_playing(f"{self.ctx.plugin_id}:test")
        )
