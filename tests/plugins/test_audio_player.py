"""Shared player replacement, failure isolation, and real local WAV decoding."""

import math
import struct
import wave
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEventLoop, QTimer

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.audio.defaults import BUNDLED_CUES
from nightreign_overlay.plugins.audio.plugin import AudioPlugin


@pytest.fixture
def player(store, tmp_path):
    services = ServiceRegistry()
    services.register(AppConfig, store.bind(AppConfig, "app"))
    ctx = PluginContext("audio", tmp_path, store, Translator("zh_CN"), services, EventBus())
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


def test_master_volume_scales_finite_audio_and_updates_without_restart(player, tmp_path):
    volumes, plays = [], []
    player._player = SimpleNamespace(
        stop=lambda: None,
        setSource=lambda url: None,
        play=lambda: plays.append(True),
        deleteLater=lambda: None,
    )
    player._output = SimpleNamespace(setVolume=volumes.append, deleteLater=lambda: None)
    master = player.ctx.services.require(AppConfig).master_volume
    path = tmp_path / "audio.wav"
    path.touch()
    master.set(50)
    assert player.play(str(path), 40)
    assert volumes[-1] == pytest.approx(0.2)
    master.set(0)
    assert volumes[-1] == 0
    master.set(100)
    assert volumes[-1] == pytest.approx(0.4)
    assert len(plays) == 1


def test_master_volume_scales_loop_fades_and_restored_stack_entries(player, tmp_path, monkeypatch):
    from PyQt6.QtMultimedia import QMediaPlayer

    import nightreign_overlay.plugins.audio.plugin as module

    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    volumes = []
    player._loop_player = SimpleNamespace(
        stop=lambda: None,
        setSource=lambda url: None,
        play=lambda: None,
        playbackState=lambda: QMediaPlayer.PlaybackState.PlayingState,
        position=lambda: 123,
        deleteLater=lambda: None,
    )
    player._loop_output = SimpleNamespace(setVolume=volumes.append, deleteLater=lambda: None)
    path = tmp_path / "loop.wav"
    path.touch()
    master = player.ctx.services.require(AppConfig).master_volume
    master.set(50)
    assert player.play_loop(str(path), 80, fade_in=2, owner="lower")
    assert volumes[-1] == 0
    now[0] = 1
    player._fade_step()
    assert volumes[-1] == pytest.approx(0.2)
    master.set(0)
    now[0] = 2
    player._fade_step()
    assert volumes[-1] == 0
    master.set(25)
    assert volumes[-1] == pytest.approx(0.2)
    assert player.play_loop(str(path), 40, owner="upper")
    assert volumes[-1] == pytest.approx(0.1)
    player.stop_loop("upper", fade_out=2)
    now[0] = 3
    player._fade_step()
    assert volumes[-1] == pytest.approx(0.05)
    master.set(50)
    assert volumes[-1] == pytest.approx(0.1)
    now[0] = 4
    player._fade_step()
    assert player._loop_stack.top.owner == "lower"
    assert volumes[-1] == 0
    now[0] = 6
    player._fade_step()
    assert volumes[-1] == pytest.approx(0.4)


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


@pytest.mark.parametrize("preset", BUNDLED_CUES.values(), ids=lambda preset: preset.filename)
def test_bundled_mp3_decodes_and_advances_with_output_muted(player, preset, qapp):
    player._ensure_player()
    player._output.setMuted(True)
    errors = []
    player._player.errorOccurred.connect(lambda *args: errors.append(args))
    assert player.play(str(preset.path))
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if errors or player._player.position() > 0 else None)
    poll.start(10)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(3000)
    loop.exec()
    poll.stop()
    timeout.stop()
    assert not errors
    assert player._player.duration() > 0 and player._player.position() > 0
