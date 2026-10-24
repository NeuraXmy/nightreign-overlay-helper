"""Shared finite and stack-based looping audio players."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtMultimedia import QMediaPlayer

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.audio.loop_stack import LoopAudioEntry, LoopAudioStack


class AudioPlugin(Plugin, AudioApi):
    manifest = PluginManifest(
        id="audio", kind=PluginKind.INFRASTRUCTURE, settings_scope=SettingsScope.HIDDEN, order=-10
    )

    def on_load(self) -> None:
        self._app_config = self.ctx.services.require(AppConfig)
        self._app_config.master_volume.valueChanged.connect(self._apply_master_volume)
        self._finite_volume = 0.0
        self._loop_volume = 0.0
        self._player: Any = None
        self._output: Any = None
        self._owner = ""
        self._loop_player: Any = None
        self._loop_output: Any = None
        self._loop_stack = LoopAudioStack()
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(30)
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_start = 0.0
        self._fade_duration = 0.0
        self._fade_from = 0.0
        self._fade_to = 0.0
        self._fade_action = ""
        self._fade_owner = ""
        self.ctx.provide(AudioApi, self)

    def _apply_master_volume(self, *_args: object) -> None:
        gain = self._app_config.master_volume.value / 100
        if self._output is not None:
            self._output.setVolume(self._finite_volume * gain)
        if self._loop_output is not None:
            self._loop_output.setVolume(self._loop_volume * gain)

    def _set_loop_volume(self, volume: float) -> None:
        self._loop_volume = volume
        self._loop_output.setVolume(volume * self._app_config.master_volume.value / 100)

    def on_activate(self) -> None:
        if self.ctx.services.get(AudioApi) is None:
            self.ctx.provide(AudioApi, self)

    def _ensure_player(self) -> None:
        if self._player is not None:
            return
        from PyQt6.QtMultimedia import QAudioOutput

        self._output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.errorOccurred.connect(self._on_finite_error)

    _ensure_finite = _ensure_player

    def _ensure_loop(self) -> None:
        if self._loop_player is not None:
            return
        from PyQt6.QtMultimedia import QAudioOutput

        self._loop_output = QAudioOutput(self)
        self._loop_player = QMediaPlayer(self)
        self._loop_player.setAudioOutput(self._loop_output)
        self._loop_player.setLoops(QMediaPlayer.Loops.Infinite)
        self._loop_player.errorOccurred.connect(self._on_loop_error)
        self._loop_player.mediaStatusChanged.connect(self._on_loop_media_status)

    def _on_loop_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._loop_stack.top is not None:
            position = self._loop_stack.top.position_ms
            if position > 0:
                self._loop_player.setPosition(position)

    def _on_finite_error(self, *_args: object) -> None:
        self.ctx.log.warning("Audio playback failed: %s", self._player.errorString())
        self.stop()

    def _on_loop_error(self, *_args: object) -> None:
        self.ctx.log.warning("Looping audio playback failed: %s", self._loop_player.errorString())
        if self._loop_stack.top is not None:
            self.stop_loop(self._loop_stack.top.owner)

    @staticmethod
    def _valid_path(path: str) -> Path | None:
        candidate = Path(path) if path else None
        return candidate if candidate is not None and candidate.is_file() else None

    def play(self, path: str, volume: int = 100, *, owner: str = "") -> bool:
        candidate = self._valid_path(path)
        if candidate is None:
            if path:
                self.ctx.log.warning("Audio file is unavailable: %s", path)
            return False
        try:
            self._ensure_player()
            self.stop()
            self._owner = owner
            self._finite_volume = max(0, min(volume, 100)) / 100
            self._output.setVolume(self._finite_volume * self._app_config.master_volume.value / 100)
            self._player.setSource(QUrl.fromLocalFile(str(candidate.resolve())))
            self._player.play()
            return True
        except Exception:
            self.ctx.log.exception("Could not play audio: %s", path)
            self.stop()
            return False

    def stop(self, owner: str | None = None) -> None:
        if owner is not None and owner != self._owner:
            return
        self._owner = ""
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())

    def is_playing(self, owner: str | None = None) -> bool:
        return (
            self._player is not None
            and (owner is None or owner == self._owner)
            and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

    def play_loop(self, path: str, volume: int = 100, fade_in: float = 0, *, owner: str = "") -> bool:
        candidate = self._valid_path(path)
        if candidate is None:
            if path:
                self.ctx.log.warning("Looping audio file is unavailable: %s", path)
            return False
        self._ensure_loop()
        previous_top = self._loop_stack.top
        is_playing = self._loop_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if previous_top is not None and is_playing:
            previous_top.position_ms = self._loop_player.position()
        if self._fade_action == "pop" and self._fade_owner:
            self._loop_stack.remove(self._fade_owner)
            self._fade_owner = ""
        self._cancel_fade()
        entry = LoopAudioEntry(
            owner,
            str(candidate.resolve()),
            max(0, min(volume, 100)),
            max(0, fade_in),
        )
        self._loop_stack.put(entry)
        self._play_loop_top()
        return True

    def set_loop_fade_out(self, owner: str, seconds: float) -> None:
        self._loop_stack.set_fade_out(owner, seconds)

    def is_loop_playing(self, owner: str) -> bool:
        return bool(
            self._loop_stack.top is not None
            and self._loop_stack.top.owner == owner
            and self._loop_player is not None
            and self._loop_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

    def stop_loop(self, owner: str, fade_out: float = 0) -> None:
        entry = self._loop_stack.get(owner)
        if entry is None:
            return
        if self._loop_stack.top is not entry:
            self._loop_stack.remove(owner)
            return
        self._fade_owner = owner
        if fade_out > 0 and self._loop_output is not None:
            self._begin_fade(0.0, fade_out, "pop")
        else:
            self._pop_loop_top()

    def _play_loop_top(self) -> None:
        entry = self._loop_stack.top
        if entry is None:
            self._loop_player.stop()
            self._loop_player.setSource(QUrl())
            return
        self._loop_player.setSource(QUrl.fromLocalFile(entry.path))
        target = entry.volume / 100
        # A cue becomes audible only after the previous top has fully faded
        # out. Every newly audible top uses its own fade-in, including a cue
        # restored from below another owner in the stack.
        self._set_loop_volume(0 if entry.fade_in > 0 else target)
        self._loop_player.play()
        if entry.fade_in > 0:
            self._begin_fade(target, entry.fade_in, "")

    def _pop_loop_top(self) -> None:
        self._cancel_fade()
        if self._loop_stack.top is not None:
            self._loop_stack.remove(self._loop_stack.top.owner)
        if self._loop_player is not None:
            self._loop_player.stop()
            self._loop_player.setSource(QUrl())
        self._play_loop_top()

    def _begin_fade(self, target: float, seconds: float, action: str) -> None:
        self._fade_from = self._loop_volume
        self._fade_to = target
        self._fade_start = time.monotonic()
        self._fade_duration = seconds
        self._fade_action = action
        self._fade_timer.start()

    def _fade_step(self) -> None:
        progress = min(1.0, (time.monotonic() - self._fade_start) / self._fade_duration)
        self._set_loop_volume(self._fade_from + (self._fade_to - self._fade_from) * progress)
        if progress >= 1:
            action = self._fade_action
            self._cancel_fade()
            if action == "pop":
                self._loop_stack.remove(self._fade_owner)
                self._fade_owner = ""
                self._loop_player.stop()
                self._loop_player.setSource(QUrl())
                self._play_loop_top()

    def _cancel_fade(self) -> None:
        self._fade_timer.stop()
        self._fade_action = ""

    def on_deactivate(self) -> None:
        self.stop()
        self._cancel_fade()
        self._loop_stack.clear()
        for player in (self._loop_player, self._player):
            if player is not None:
                player.stop()
                player.setSource(QUrl())
        for resource in (self._player, self._output, self._loop_player, self._loop_output):
            if resource is not None:
                resource.deleteLater()
        self._player = self._output = self._loop_player = self._loop_output = None
