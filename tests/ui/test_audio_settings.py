"""Audio settings file actions, bindings, previews, and feature group placement."""

import pytest
from PyQt6.QtWidgets import QFileDialog, QWidget

from nightreign_overlay.core import i18n
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.art_timer.plugin import ArtTimerPlugin
from nightreign_overlay.plugins.audio.api import AudioApi, AudioNotifications
from nightreign_overlay.plugins.day_timer.plugin import DayTimerPlugin
from nightreign_overlay.plugins.input.plugin import InputPlugin
from nightreign_overlay.plugins.rain_timer.plugin import RainTimerPlugin
from nightreign_overlay.ui.components.audio_settings import AudioSettingCard, audio_section
from tests.support.paths import PROJECT_ROOT
from tests.support.qt import delete_qobjects


def context(plugin_id, store, services, language="zh_CN"):
    translator = Translator(language)
    translator.load_dir("core", PROJECT_ROOT / "src/nightreign_overlay/resources/i18n")
    root = PROJECT_ROOT / "src/nightreign_overlay/plugins" / plugin_id
    translator.load_dir(plugin_id, root / "i18n")
    return PluginContext(plugin_id, root, store, translator, services, EventBus())


def test_selection_change_clear_preview_and_reset(store, qapp, monkeypatch):
    services = ServiceRegistry()
    calls = []

    class Preview(AudioApi):
        def __init__(self):
            self.playing = False

        def play(self, path, volume=100, *, owner=""):
            calls.append((path, volume, owner))
            self.playing = True
            return True

        def stop(self, owner=None):
            self.playing = False

        def is_playing(self, owner=None):
            return self.playing

    preview = Preview()
    services.register(AudioApi, preview, owner="audio")
    ctx = context("rain_timer", store, services)
    monkeypatch.setattr(i18n, "_translator", ctx._translator)
    notifications = AudioNotifications(ctx, ("start", "end"))
    section = audio_section(notifications, ("end",))
    card = section.findChildren(AudioSettingCard)[0]
    cue = card.cue
    assert card.slider.value() == 100 and card.spinBox.value() == 0.0
    assert not card.clearButton.isEnabled() and card.testButton.isEnabled()
    assert card.switchButton.isChecked()
    assert card.clearButton.text() == i18n.tr("audio.restore_default")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: ("提示音.wav", ""))
    card.selectButton.click()
    assert cue.path.value == "提示音.wav"
    card.slider.setValue(42)
    card.spinBox.setValue(1.5)
    card.testButton.click()
    assert calls == [("提示音.wav", 42, "rain_timer:test")]
    assert card.testButton.text() == i18n.tr("audio.stop_test")
    card.testButton.click()
    assert card.testButton.text() == i18n.tr("audio.test")
    assert cue.volume.value == 42 and cue.seconds.value == 1.5
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: ("other.mp3", ""))
    card.selectButton.click()
    assert cue.path.value == "other.mp3"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: ("", ""))
    card.selectButton.click()
    assert cue.path.value == "other.mp3"
    card.clearButton.click()
    assert cue.path.value == "" and card.testButton.isEnabled()
    card.testButton.click()
    assert calls[-1] == (notifications.default_path(cue), 42, "rain_timer:test")
    card.switchButton.setChecked(False)
    assert not cue.enabled.value and not card.testButton.isEnabled()
    assert not preview.playing
    ctx.reset_configs()
    assert card.slider.value() == 100 and card.spinBox.value() == 0.0
    assert card.switchButton.isChecked() and card.testButton.isEnabled()
    delete_qobjects(section)


@pytest.mark.parametrize("language", ["zh_CN", "zh_TW", "en_US", "ja_JP"])
@pytest.mark.parametrize("cls,count", [(DayTimerPlugin, 5), (RainTimerPlugin, 3), (ArtTimerPlugin, 2)])
def test_audio_is_last_section_with_localized_titles(store, qapp, monkeypatch, cls, count, language):
    services = ServiceRegistry()
    input_plugin = InputPlugin(context("input", store, services, language))
    input_plugin.on_load()
    plugin = cls(context(cls.manifest.id, store, services, language))
    monkeypatch.setattr(i18n, "_translator", plugin.ctx._translator)
    plugin.on_load()
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    section = panel.sectionLayout.itemAt(panel.sectionLayout.count() - 1).widget()
    cards = section.findChildren(AudioSettingCard)
    assert section.titleLabel.text() == i18n.tr("audio.title")
    assert section.titleLabel.text() != "audio.title"
    assert len(cards) == count
    for card in cards:
        assert card.titleLabel.text() and not card.titleLabel.text().startswith("audio.")
        assert card.selectButton.text() == i18n.tr("audio.select")
        assert card.contentLabel.text() == i18n.tr("audio.builtin")
        assert card.switchButton.isChecked() and card.testButton.isEnabled()
        assert card.spinBox.value() == card.cue.seconds.default
    delete_qobjects(parent)
