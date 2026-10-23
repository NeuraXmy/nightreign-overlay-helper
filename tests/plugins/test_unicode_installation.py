"""Load the actual application resources from a Unicode installation directory."""

import os
import subprocess
import sys
from shutil import copytree, ignore_patterns

from tests.support.paths import PROJECT_ROOT


def test_plugins_fonts_models_and_native_library_load_from_unicode_installation(tmp_path):
    root = tmp_path / "黑夜助手 テスト é😀"
    copytree(
        PROJECT_ROOT / "src/nightreign_overlay",
        root / "nightreign_overlay",
        ignore=ignore_patterns("__pycache__", "*.pyc"),
    )
    script = r"""
import ctypes
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.events import EventBus
from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.core.paths import PACKAGE_DIR, resource_path
from nightreign_overlay.core.services import ServiceRegistry
from nightreign_overlay.plugin import PluginManager, PluginState
from nightreign_overlay.plugins.art_timer.detector import ArtDetector
from nightreign_overlay.plugins.audio.defaults import BUNDLED_CUES
from nightreign_overlay.plugins.day_timer.detector import LANGUAGES, DayDetector
from nightreign_overlay.plugins.debuff_timer.detector import DebuffDetector
from nightreign_overlay.plugins.hp_marker.material import MaterialModel
from nightreign_overlay.plugins.map_detect.image_utils import get_font
from nightreign_overlay.plugins.map_detect.poi_cnn import PoiCnn
from nightreign_overlay.ui.theme import app_icon

assert PACKAGE_DIR.is_relative_to(root)
assert len(BUNDLED_CUES) == 10
assert all(cue.path.is_relative_to(root) and cue.path.is_file() for cue in BUNDLED_CUES.values())
app = QApplication([])
translator = Translator("zh_CN")
translator.load_dir("core", resource_path("i18n"))
assert translator.tr("core", "nav.home") != "nav.home"
store = ConfigStore(root / "settings.yaml")
manager = PluginManager(store, translator, ServiceRegistry(), EventBus())
manager.discover()
expected = {
    "art_timer", "audio", "capture", "day_timer", "hp_marker", "hud",
    "input",
    "map_detect",
    "p2p_latency",
    "rain_timer",
    "region",
    "commendation",
    "steam_recovery",
    "entertainment",
    "debuff_timer",
}
manager.load_all()
assert {record.id for record in manager.records()} == expected
assert all(record.state == PluginState.INACTIVE for record in manager.records())
assert all(record.plugin is not None for record in manager.records())
plugins = PACKAGE_DIR / "plugins"
days = DayDetector(plugins / "day_timer/templates")
assert all(days.available(language) for language in LANGUAGES)
assert not ArtDetector(plugins / "art_timer/icons").missing()
assert len(DebuffDetector(plugins / "debuff_timer/icons").templates) == 40
font = get_font(20)
assert font.getbbox("Nightreign")[2] > 0
assert not app_icon().isNull()
assert not QImage(str(plugins / "map_detect/data/maps/0.jpg")).isNull()
cnn = PoiCnn()
base, corner = cnn.predict(np.zeros((750, 750, 3), np.uint8), [(375, 375)])
assert base.shape == (1, 15) and corner.shape == (1, 12)
material = MaterialModel()
assert material._material.get_providers() == ["CPUExecutionProvider"]
assert material._cap.get_providers() == ["CPUExecutionProvider"]
if sys.platform == "win32":
    library = ctypes.CDLL(str(plugins / "capture/native/MaaWin32Screencap.dll"))
    assert library.MaaWSManagerCreate
manager.shutdown()
print("Unicode installation resources loaded")
"""
    environment = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONIOENCODING": "utf-8",
        "NROH_DATA_DIR": str(root / "userdata"),
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(root)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Unicode installation resources loaded" in result.stdout
