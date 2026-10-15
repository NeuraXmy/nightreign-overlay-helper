"""Compare every detection result and internal history with isolated legacy source."""

from __future__ import annotations

import ast
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import yaml
from PIL import Image

from nightreign_overlay.plugins.hp_marker.config import HpDetectionSettings
from nightreign_overlay.plugins.hp_marker.detector import HpDetector
from tests.support.paths import PROJECT_ROOT

_OLD = PROJECT_ROOT.parent / "nightreign-overlay-helper"
pytestmark = pytest.mark.skipif(not (_OLD / "src/detector/hp_detector.py").exists(), reason="legacy absent")


def _legacy(monkeypatch, config, image_box):
    source = _OLD / "src/detector/hp_detector.py"
    module = ModuleType("legacy_hp_audit")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    module.__dict__.update(
        Config=SimpleNamespace(get=lambda: config),
        ScreencapEngine=object,
        debug=lambda *args: None,
        grab_region=lambda *args, **kwargs: Image.fromarray(image_box[0]),
        resize_by_height_keep_aspect_ratio=lambda img, height: img.resize(
            (int(height * (img.width / img.height)), height), Image.Resampling.LANCZOS
        ),
    )
    tree = ast.parse(source.read_text())
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src"))
    ]
    exec(compile(tree, str(source), "exec"), module.__dict__)
    return module


def test_detection_defaults_match_old_config():
    values = yaml.safe_load((_OLD / "config.yaml").read_text())
    config = HpDetectionSettings()
    assert all(getattr(config, name) == values[name] for name in config.__dataclass_fields__)


@pytest.mark.parametrize("height,history", [(15, 10), (9, 6), (23, 15)])
def test_peak_clustering_smoothing_and_failure_history_parity(monkeypatch, height, history):
    settings = replace(HpDetectionSettings(), hpbar_recent_length_count=history)
    box = [None]
    old = _legacy(monkeypatch, settings, box)
    before, after = old.HpDetector(), HpDetector()
    widths = [500] * 14 + [502, 498, 503, 500] * 2 + [650] * 14 + [None] * 22
    outputs = []
    for index, width in enumerate(widths):
        image = np.zeros((height, height * 125, 3), np.uint8)
        if width is not None:
            # Two well-separated peaks on the midline, with no colour assumptions.
            image[:, 50:65] = (200, 40, 30)
            image[:, width : width + 15] = (50, 230, 60)
        box[0] = image
        result = before.detect(None, old.HpDetectParam((0, 0, 5, height), keep_last_valid=bool(index % 2)))
        new = after.detect(image, settings)
        assert result.hpbar_length == new, (index, width)
        assert before.recent_lengths == after.recent_lengths
        assert before.last_valid_length == after.last_valid_length
        assert before.stable_count == after.stable_count
        outputs.append(new)
    assert any(length is not None for length in outputs)
    assert len(after.recent_lengths) == history
