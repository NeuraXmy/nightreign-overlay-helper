"""Source/build/frozen helper resolution is independent of the launch directory."""

from pathlib import Path

import pytest

from nightreign_overlay.plugins.p2p_latency import service


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv("NIGHTREIGN_P2P_HELPER_PATH", raising=False)
    monkeypatch.setattr(service.sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        service, "__file__", str(tmp_path / "src/nightreign_overlay/plugins/p2p_latency/service.py")
    )
    return tmp_path


@pytest.mark.parametrize(
    "directory",
    [
        "bin",
        "build/p2p/bin",
        "native/NightreignP2PHelper/bin/Debug/net8.0-windows/win-x64",
        "native/NightreignP2PHelper/bin/Release/net8.0-windows/win-x64/publish",
        "native/NightreignP2PHelper/bin/Release/net8.0-windows/win-x64",
    ],
)
def test_source_resolves_each_supported_output(project, monkeypatch, directory):
    helper = project / directory / service.HELPER_FILENAME
    helper.parent.mkdir(parents=True)
    helper.touch()
    monkeypatch.chdir(project.parent)
    assert service.resolve_helper_path() == helper


def test_packaged_build_output_precedes_native_build(project):
    for directory in ("build/p2p/bin", "native/NightreignP2PHelper/bin/Release/net8.0-windows/win-x64"):
        helper = project / directory / service.HELPER_FILENAME
        helper.parent.mkdir(parents=True)
        helper.touch()
    assert service.resolve_helper_path() == project / "build/p2p/bin" / service.HELPER_FILENAME


def test_missing_helper_returns_expected_build_destination(project):
    assert service.resolve_helper_path() == project / "bin" / service.HELPER_FILENAME


def test_explicit_override_remains_authoritative(project, monkeypatch):
    override = project / "custom" / service.HELPER_FILENAME
    monkeypatch.setenv("NIGHTREIGN_P2P_HELPER_PATH", str(override))
    assert service.resolve_helper_path() == override


def test_frozen_only_uses_bundled_helper(project, monkeypatch):
    monkeypatch.setattr(service.sys, "frozen", True, raising=False)
    monkeypatch.setattr(service.sys, "executable", str(project / "dist/app.exe"))
    assert service.resolve_helper_path() == Path(project / "dist/bin" / service.HELPER_FILENAME)
