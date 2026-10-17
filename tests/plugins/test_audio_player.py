"""Shared player replacement, failure isolation, and real local WAV decoding."""

import math
import struct
import wave
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEventLoop, QTimer

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.audio.plugin import AudioPlugin


@pytest.fixture
def player(store, tmp_path):
    ctx = PluginContext("audio", tmp_path, store, Translator("zh_CN"), ServiceRegistry(), EventBus())
    plugin = AudioPlugin(ctx)
    plugin.on_load()
    yield plugin
    plugin.on_deactivate()
    ctx.release()


def test_replacement_volume_and_owner_cleanup(player, tmp_path):
    calls = []
    player._player = SimpleNamespace(
        stop=lambda: calls.append("stop"),
        setSource=lambda url: calls.append(url),
        play=lambda: calls.append("play"),
        deleteLater=lambda: None,
    )
    player._output = SimpleNamespace(setVolume=lambda value: calls.append(value), deleteLater=lambda: None)
    path = tmp_path / "audio.wav"
    path.touch()
    assert player.ctx.services.require(AudioApi) is player
    assert player.play(str(path), 40, owner="day_timer")
    assert calls[0] == "stop" and calls[-1] == "play" and 0.4 in calls
    assert player.play(str(path), 70, owner="rain_timer")
    before = len(calls)
    player.stop("day_timer")
    assert len(calls) == before
    player.stop("rain_timer")
    assert calls[-2] == "stop"


def test_missing_audio_and_backend_failure_are_safe(player, tmp_path, monkeypatch):
    assert not player.play("")
    assert not player.play(str(tmp_path / "missing.wav"))
    assert player._player is None
    path = tmp_path / "audio.wav"
    path.touch()

    def fail():
        raise RuntimeError("no audio backend")

    monkeypatch.setattr(player, "_ensure_player", fail)
    assert not player.play(str(path))


def test_real_decode_corrupt_file_and_recovery(player, tmp_path, qapp):
    # Generate an original pure tone; tests need no downloads or licensed audio assets.
    path = tmp_path / "提示音.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        output.writeframes(
            b"".join(
                struct.pack("<h", round(1000 * math.sin(2 * math.pi * 660 * i / 22050))) for i in range(4410)
            )
        )
    player._ensure_player()
    player._output.setMuted(True)
    errors = []
    player._player.errorOccurred.connect(lambda *args: errors.append(args))

    def wait_until(predicate):
        loop = QEventLoop()
        poll = QTimer()
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        poll.start(10)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        poll.stop()
        assert predicate()

    bad = tmp_path / "corrupt.wav"
    bad.write_bytes(b"not an audio file")
    assert player.play(str(bad))
    wait_until(lambda: bool(errors))
    assert player._player.source().isEmpty()
    errors.clear()
    assert player.play(str(path), 35)
    wait_until(lambda: player._player.duration() > 0 or bool(errors))
    assert not errors
    assert player._player.duration() >= 190
    assert player._output.volume() == pytest.approx(0.35)
