from pathlib import Path

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.audio.api import AudioApi
from nightreign_overlay.plugins.entertainment.plugin import EntertainmentPlugin
from nightreign_overlay.plugins.input.api import HotkeyApi
from nightreign_overlay.plugins.region.api import RegionApi


class _Region(RegionApi):
    def __init__(self):
        self.rect = QRect(0, 0, 320, 160)

    def region(self, key):
        return self.rect

    def save_region(self, key, rect):
        self.rect = rect

    def clear_region(self, key):
        self.rect = None


class _Audio(AudioApi):
    def set_loop_fade_out(self, owner, seconds):
        pass

    def stop_loop(self, owner, fade_out=0):
        pass

    def is_loop_playing(self, owner):
        return False


class _Hotkeys(HotkeyApi):
    def register(self, action_id, default, callback):
        pass

    def unregister(self, action_id):
        pass

    def binding(self, action_id, default):
        return default


def test_plugin_registers_default_region_and_builds_settings(store, qapp, tmp_path):
    services = ServiceRegistry()
    region = _Region()
    services.register(RegionApi, region, owner="region")
    services.register(AudioApi, _Audio(), owner="audio")
    services.register(HotkeyApi, _Hotkeys(), owner="input")
    translator = Translator("zh_CN")
    translator.load_dir("entertainment", Path("src/nightreign_overlay/plugins/entertainment/i18n"))
    translator.load_dir("core", Path("src/nightreign_overlay/resources/i18n"))
    context = PluginContext("entertainment", tmp_path, store, translator, services, EventBus())
    plugin = EntertainmentPlugin(context)
    plugin.on_load()
    plugin.on_activate()
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)

    # Migrate the old fake calibration so the region falls back to automatic 16:9 geometry.
    assert region.rect is None
    assert panel is not None

    plugin.on_deactivate()
    context.release()
    parent.deleteLater()


def test_state_transition_requires_three_consecutive_matching_detections(store, qapp, tmp_path, monkeypatch):
    import nightreign_overlay.plugins.entertainment.plugin as module

    services = ServiceRegistry()
    region = _Region()
    services.register(RegionApi, region, owner="region")
    services.register(AudioApi, _Audio(), owner="audio")
    services.register(HotkeyApi, _Hotkeys(), owner="input")
    translator = Translator("zh_CN")
    translator.load_dir("entertainment", Path("src/nightreign_overlay/plugins/entertainment/i18n"))
    translator.load_dir("core", Path("src/nightreign_overlay/resources/i18n"))
    context = PluginContext("entertainment", tmp_path, store, translator, services, EventBus())
    plugin = EntertainmentPlugin(context)
    plugin.on_load()
    plugin._active = True
    plugin._generation = 1

    from nightreign_overlay.plugins.entertainment.detector import Teammate

    down = Teammate(True, True, 1, 1.0, (0.0, 0.0))
    upright = Teammate(True, False, 0, 1.0, (0.0, 0.0))
    calls = []
    monkeypatch.setattr(plugin, "_start_loop", lambda: calls.append("start"))
    monkeypatch.setattr(module, "should_start", lambda *_: True)
    for _ in range(2):
        plugin._on_completed((1, (down, upright)), region.rect)
    assert calls == []
    plugin._on_completed((1, (down, upright)), region.rect)
    assert calls == ["start"]
    context.release()
