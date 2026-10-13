"""Migration audit against the sibling legacy source, skipped in standalone rewrite checkouts.

Both implementations run against identical bundled images and RNG seeds. This checks numerical/rendering
parity rather than claiming accuracy on live game frames. Legacy modules are isolated from their old UI.
"""

from __future__ import annotations

import ast
import logging
import random
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from nightreign_overlay.core.paths import user_data_dir
from nightreign_overlay.plugins.capture.api import normalize_image
from nightreign_overlay.plugins.map_detect import detector as new
from nightreign_overlay.plugins.map_detect.config import MapDetectionSettings

_OLD = Path(__file__).resolve().parents[2] / "nightreign-overlay-helper"
pytestmark = pytest.mark.skipif(not (_OLD / "src/detector/map_detector.py").exists(), reason="legacy absent")


def _load(name, path, values, monkeypatch, selected=None):
    module = ModuleType(name)
    module.__dict__.update(values)
    monkeypatch.setitem(sys.modules, name, module)
    tree = ast.parse(path.read_text())
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src"))
        and (selected is None or (isinstance(node, ast.FunctionDef) and node.name in selected))
    ]
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


@pytest.fixture
def legacy(monkeypatch, tmp_path):
    logger = logging.getLogger("legacy_map_audit")
    values = {
        "get_data_path": lambda path: str(_OLD / "data" / path),
        "get_appdata_path": lambda path: str(tmp_path / path),
        "info": logger.info,
        "warning": logger.warning,
        "error": logger.error,
        "debug": logger.debug,
        "ScreencapEngine": object,
        "Config": SimpleNamespace(get=lambda: MapDetectionSettings()),
        "cv2": cv2,
        "np": np,
        "Image": Image,
        "ImageDraw": ImageDraw,
        "ImageFont": ImageFont,
        "font_cache": {},
        "DEFAULT_FONT_PATH": str(_OLD / "data/fonts/SourceHanSansSC-Normal.otf"),
    }
    utils = _load(
        "legacy_map_utils",
        _OLD / "src/detector/utils.py",
        values,
        monkeypatch,
        {
            "get_font",
            "get_text_size",
            "paste_cv2",
            "draw_icon",
            "draw_text",
            "match_template",
            "align_image",
            "normalize_image",
        },
    )
    info = _load("legacy_map_info", _OLD / "src/detector/map_info.py", {}, monkeypatch)
    values.update(
        {
            key: getattr(info, key)
            for key in ("Position", "Construct", "MapPattern", "STD_MAP_SIZE", "load_map_info")
        }
    )
    values.update(
        {
            key: getattr(utils, key)
            for key in ("paste_cv2", "draw_icon", "draw_text", "match_template", "align_image")
        }
    )
    old = _load("legacy_map_detector", _OLD / "src/detector/map_detector.py", values, monkeypatch)
    user_data_dir.cache_clear()
    yield old, utils
    user_data_dir.cache_clear()


def test_bundled_assets_are_exact_copies():
    root = Path(new.__file__).parent / "data"
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root)
            assert path.read_bytes() == (_OLD / "data" / relative).read_bytes(), str(relative)


def test_hdr_preprocessing_and_csv_models(legacy):
    old, utils = legacy
    image = np.random.default_rng(45).integers(0, 256, (100, 100, 3), dtype=np.uint8)
    assert np.array_equal(normalize_image(image), np.asarray(utils.normalize_image(Image.fromarray(image))))
    before, after = old.MapDetector(), new.MapDetector()
    assert len(before.info.patterns) == len(after.info.patterns) > 0
    assert before.info.pos_dict == after.info.pos_dict
    assert before.info.tgh_pos_dict == after.info.tgh_pos_dict
    assert before.info.possible_poi_types == after.info.possible_poi_types
    assert [vars(p) | {"pos_constructions": None} for p in before.info.patterns] == [
        vars(p) | {"pos_constructions": None} for p in after.info.patterns
    ]


@pytest.mark.parametrize("terrain", range(6))
def test_full_map_terrain_nightlord_poi_and_candidate_parity(legacy, terrain):
    old, _ = legacy
    before, after = old.MapDetector(), new.MapDetector()
    image = new.MAP_BGS[terrain].copy()
    assert before._match_full_map(image) == after._match_full_map(image)
    assert before._match_earth_shifting(image) == after._match_earth_shifting(image)
    assert before._match_nightlord(image) == after._match_nightlord(image)
    random.seed(118)
    cv2.setRNGSeed(118)
    left = before._match_map_pattern(image, terrain, 5)
    random.seed(118)
    cv2.setRNGSeed(118)
    right = after._match_map_pattern(image, terrain, 5)
    assert [(p.pattern.id, p.nightlord, p.error, p.score) for p in left] == [
        (p.pattern.id, p.nightlord, p.error, p.score) for p in right
    ]
    for index, (a, b) in enumerate(zip(left, right, strict=True)):
        assert (
            before._draw_overlay_image(a, (300, 300), index).tobytes()
            == after._draw_overlay_image(b, (300, 300), index).tobytes()
        )


def test_all_poi_icon_pixels_and_crystal_layouts(legacy):
    import os

    import yaml

    from nightreign_overlay.plugins.map_detect.overlay import MapInfoOverlay

    old, utils = legacy
    before, after = old.MapDetector(), new.MapDetector()
    assert before.all_poi_images.keys() == after.all_poi_images.keys()
    for key in before.all_poi_images:
        assert before.all_poi_images[key].tobytes() == after.all_poi_images[key].tobytes()

    tree = ast.parse((_OLD / "src/ui/map_overlay.py").read_text())
    overlay = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MapOverlayWidget"
    )
    method = next(
        node
        for node in overlay.body
        if isinstance(node, ast.FunctionDef) and node.name == "init_crystal_layout_imgs"
    )
    namespace = {
        "os": os,
        "Image": Image,
        "draw_text": utils.draw_text,
        "get_data_path": lambda path: str(_OLD / "data" / path),
        "load_yaml": lambda path: yaml.safe_load(Path(path).read_text()),
        "error": logging.getLogger(__name__).error,
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), "legacy_crystal", "exec"), namespace)
    a, b = SimpleNamespace(), SimpleNamespace()
    namespace["init_crystal_layout_imgs"](a)
    MapInfoOverlay.init_crystal_layout_imgs(b)
    assert len(a.crystal_layout_imgs) == len(b.crystal_layout_imgs) == 5
    for left, right in zip(a.crystal_layout_imgs, b.crystal_layout_imgs, strict=True):
        assert left.tobytes() == right.tobytes()
