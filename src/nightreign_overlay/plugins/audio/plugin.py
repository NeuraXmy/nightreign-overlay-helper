"""Lazy Qt multimedia player; audio failures never escape into feature callbacks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QUrl

from nightreign_overlay.plugin import Plugin, PluginKind, PluginManifest, SettingsScope
from nightreign_overlay.plugins.audio.api import AudioApi


class AudioPlugin(Plugin, AudioApi):
    manifest = PluginManifest(
        id="audio", kind=PluginKind.INFRASTRUCTURE, settings_scope=SettingsScope.HIDDEN, order=-10
    )

    def on_load(self) -> None:
        self._player: Any = None
        self._output: Any = None
        self._owner = ""
        self.ctx.provide(AudioApi, self)

    def on_activate(self) -> None:
        if self.ctx.services.get(AudioApi) is None:
            self.ctx.provide(AudioApi, self)

    def _ensure_player(self) -> None:
        if self._player is not None:
            return
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

        output = QAudioOutput(self)
        player = QMediaPlayer(self)
        player.setAudioOutput(output)
        player.errorOccurred.connect(self._on_error)
        self._output, self._player = output, player

    def _on_error(self, *_args: object) -> None:
        self.ctx.log.warning("Audio playback failed: %s", self._player.errorString())
        self.stop()

    def play(self, path: str, volume: int = 100, *, owner: str = "") -> bool:
        if not path:
            return False
        try:
            if not Path(path).is_file():
                self.ctx.log.warning("Audio file is unavailable: %s", path)
                return False
            self._ensure_player()
            self.stop()
            self._owner = owner
            self._output.setVolume(max(0, min(volume, 100)) / 100)
            self._player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
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
            try:
                self._player.stop()
                self._player.setSource(QUrl())
            except Exception:
                self.ctx.log.exception("Could not stop audio")

    def on_deactivate(self) -> None:
        self.stop()
        for resource in (self._player, self._output):
            if resource is not None:
                resource.deleteLater()
        self._player = self._output = None
