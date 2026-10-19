"""Publishing must attach the original program ZIP and its matching source ZIP."""

import hashlib
import json
import zipfile

import pytest
from scripts.validate_release_assets import validate_assets


@pytest.fixture
def assets(tmp_path):
    snapshot = b"matching project source ZIP"
    manifest = json.dumps(
        {"project": {"archive": "project.zip", "sha256": hashlib.sha256(snapshot).hexdigest()}}
    ).encode()
    runtime = tmp_path / "nightreign-overlay-helper-v1.0.1-windows-x64.zip"
    sources = tmp_path / "v1.0.1-sources.zip"
    with zipfile.ZipFile(runtime, "w") as archive:
        for name in ("nightreign-overlay-helper.exe", "bin/NightreignP2PHelper.exe", "LICENSE"):
            archive.writestr("nightreign-overlay-helper/" + name, b"runtime file")
        archive.writestr("nightreign-overlay-helper/licenses/source-manifest.json", manifest)
    with zipfile.ZipFile(sources, "w") as archive:
        archive.writestr("manifest.json", manifest)
        archive.writestr("project.zip", snapshot)
    return tmp_path, runtime, sources


def test_original_matching_archives_are_publishable(assets):
    directory, _, _ = assets
    validate_assets(directory, "v1.0.1")


def test_auto_extracted_artifacts_cannot_be_published(assets):
    directory, runtime, sources = assets
    for path in (runtime, sources):
        with zipfile.ZipFile(path) as archive:
            archive.extractall(directory)
        path.unlink()
    with pytest.raises(ValueError, match="Expected release ZIPs"):
        validate_assets(directory, "v1.0.1")


def test_missing_program_cannot_be_published(assets):
    directory, runtime, _ = assets
    runtime.unlink()
    with pytest.raises(ValueError, match="Expected release ZIPs"):
        validate_assets(directory, "v1.0.1")


def test_mismatched_source_cannot_be_published(assets):
    directory, _, sources = assets
    with zipfile.ZipFile(sources, "w") as archive:
        archive.writestr("manifest.json", b'{"project": {}}')
    with pytest.raises(ValueError, match="manifests do not match"):
        validate_assets(directory, "v1.0.1")
