"""Constrained CNN decoding, batched CPU inference, and manual recognition regressions."""

from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from nightreign_overlay.plugins.map_detect.config import MapDetectionSettings
from nightreign_overlay.plugins.map_detect.detector import MapDetector, MapDetectParam
from nightreign_overlay.plugins.map_detect.poi_cnn import PoiCnn
from tests.support.paths import MAP_CAPTURE_DIR


@pytest.fixture
def detector():
    return MapDetector(MapDetectionSettings(poi_algorithm="cnn"))


def test_constrain_base_then_only_legal_corners(detector):
    base, corner = np.zeros(15), np.zeros(12)
    base[5] = 0.99  # Globally strongest building is forbidden here.
    base[4] = 0.8  # Ruins.
    base[1] = 0.1  # Fort.
    corner[3] = 0.9  # Death is forbidden for the allowed ruins.
    corner[1] = 0.3  # Bleed.
    corner[2] = 0.2  # Frost.
    assert detector._select_cnn_poi(base, corner, {30301, 34001, 34002})[0] == 34001
    # A high bleed probability must not select a subtype absent at this point.
    assert detector._select_cnn_poi(base, corner, {30301, 34002})[0] == 34002


def test_variants_null_and_no_candidates(detector):
    base, corner = np.zeros(15), np.ones(12)
    base[0], base[7], base[8] = 0.4, 0.3, 0.3
    assert detector._select_cnn_poi(base, corner, {0, 41000})[0] == 41000
    base[0] = 0.9
    assert detector._select_cnn_poi(base, corner, {0, 41000})[0] == 0
    assert detector._select_cnn_poi(base, corner, set()) == (0, 0.0)


def test_manual_single_point_and_batch_share_session(detector, monkeypatch):
    calls = []

    class FakeCnn:
        def predict(self, image, positions):
            calls.append(list(positions))
            base, corner = np.ones((len(positions), 15)), np.ones((len(positions), 12))
            return base, corner

    detector._poi_cnn = FakeCnn()
    positions = sorted(detector.info.all_poi_pos[(0, 0)])[:2]
    image = np.zeros((750, 750, 3), np.uint8)
    monkeypatch.setattr(detector, "_prepare_poi_image", lambda *_: (image, image))
    for selection in (positions, positions[:1]):
        result = detector.detect(
            MapDetectParam(
                map_region=(0, 0, 750, 750),
                img=image,
                earth_shifting=0,
                nightlord=0,
                poi_positions=selection,
            )
        )
        assert set(result.poi_types) == set(selection)
        for pos, ctype in result.poi_types.items():
            assert ctype in detector.info.possible_poi_types[(0, 0, pos)]
    assert calls == [positions, positions[:1]]
    assert detector._match_pois(image, image, [], 0) == {}
    assert len(calls) == 2
    detector._match_poi(image, image, positions[0], 0, 0)
    assert calls[-1] == positions[:1]


def test_template_dispatch_never_loads_cnn(detector, monkeypatch):
    detector.config = replace(detector.config, poi_algorithm="template")
    monkeypatch.setattr(detector, "_match_poi", lambda *args: (0, 123.0))
    assert detector._match_pois(None, None, [(20, 20)], 0) == {(20, 20): (0, 123.0)}
    assert detector._poi_cnn is None


def test_cpu_session_batch_single_parity_and_edge_padding():
    cnn = PoiCnn()
    image = np.random.default_rng(42).integers(0, 256, (750, 750, 3), dtype=np.uint8)
    positions = [(0, 0), (375, 375), (749, 749)]
    base, corner = cnn.predict(image, positions)
    assert base.shape == (3, 15)
    assert corner.shape == (3, 12)
    assert cnn.session.get_providers() == ["CPUExecutionProvider"]
    for i, position in enumerate(positions):
        single_base, single_corner = cnn.predict(image, [position])
        np.testing.assert_allclose(base[i], single_base[0], atol=1e-6)
        np.testing.assert_allclose(corner[i], single_corner[0], atol=1e-6)
    np.testing.assert_allclose(base.sum(axis=1), 1, atol=1e-6)
    np.testing.assert_allclose(corner.sum(axis=1), 1, atol=1e-6)


# User-confirmed hard capture remains reported by the benchmark, outside acceptance.
_CAPTURES = [path for path in sorted((MAP_CAPTURE_DIR).glob("*.jpg")) if path.name != "207_hide.jpg"]


@pytest.fixture(scope="module")
def capture_detector():
    return MapDetector(MapDetectionSettings(poi_algorithm="cnn"))


@pytest.mark.parametrize("path", _CAPTURES, ids=lambda path: path.name)
def test_cnn_capture_map_id(capture_detector, path):
    """Run the deployed ONNX backend; labels never participate in prediction."""
    image = np.array(Image.open(path).convert("RGB"))
    terrain, _ = capture_detector._match_earth_shifting(image)
    result = capture_detector._match_map_pattern(image, terrain, topk=1)[0]
    expected = {int(value) for value in path.stem.split("_")[0].split("-")}
    assert result.pattern.id in expected, f"{path.name}: id={result.pattern.id}, error={result.error}"
