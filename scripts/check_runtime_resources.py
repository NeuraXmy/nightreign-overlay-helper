"""Load release-critical models and discover plugins without a game or input hooks."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PyQt6.QtWidgets import QApplication

from nightreign_overlay.core.app_config import AppConfig
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.paths import PACKAGE_DIR
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin import PluginManager, PluginState
from nightreign_overlay.plugins.audio.defaults import BUNDLED_CUES, BUNDLED_LOOP_AUDIO, SOUNDS_DIR
from nightreign_overlay.plugins.debuff_timer.detector import DebuffDetector

EXPECTED_PLUGINS = {
    "art_timer",
    "audio",
    "capture",
    "commendation",
    "day_timer",
    "entertainment",
    "debuff_timer",
    "hp_marker",
    "hud",
    "input",
    "map_detect",
    "p2p_latency",
    "rain_timer",
    "region",
    "steam_recovery",
}


def main() -> None:
    app = QApplication.instance() or QApplication([])
    plugins = PACKAGE_DIR / "plugins"
    if len(DebuffDetector(plugins / "debuff_timer/icons").templates) != 40:
        raise RuntimeError("Status meter icon templates are incomplete")
    for cue in BUNDLED_CUES.values():
        if not cue.path.is_file() or cue.path.stat().st_size == 0:
            raise RuntimeError(f"Missing bundled voice: {cue.filename}")
    for filename in BUNDLED_LOOP_AUDIO.values():
        path = SOUNDS_DIR / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing bundled loop audio: {filename}")
    for relative in (
        "map_detect/data/poi_cnn/epoch-42.onnx",
        "hp_marker/data/material_v1.onnx",
        "hp_marker/data/cap_v1.onnx",
    ):
        session = ort.InferenceSession(str(plugins / relative), providers=["CPUExecutionProvider"])
        feeds = {}
        for value in session.get_inputs():
            shape = [size if isinstance(size, int) else 1 for size in value.shape]
            feeds[value.name] = np.zeros(shape, dtype=np.float32)
        session.run(None, feeds)
    with tempfile.TemporaryDirectory() as temporary:
        store = ConfigStore(Path(temporary) / "settings.yaml")
        services = ServiceRegistry()
        services.register(AppConfig, store.bind(AppConfig, "app"))
        manager = PluginManager(store, Translator("zh_CN"), services, EventBus())
        manager.discover()
        manager.load_all()
        records = manager.records()
        if {record.id for record in records} != EXPECTED_PLUGINS:
            raise RuntimeError("Release plugin discovery is incomplete")
        if any(record.state != PluginState.INACTIVE for record in records):
            raise RuntimeError("Release plugin loading failed")
    app.processEvents()


if __name__ == "__main__":
    main()
