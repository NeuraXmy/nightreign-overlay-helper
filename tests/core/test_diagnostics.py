"""Diagnostic archive contents, attachment fidelity, and failures during export."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest
from PIL import Image, UnidentifiedImageError

from nightreign_overlay.core.diagnostics import create_diagnostic_archive
from nightreign_overlay.meta import APP_VERSION


def test_archive_includes_logs_debug_metadata_and_distinct_original_attachments(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "logs").mkdir(parents=True)
    (root / "debug" / "hp_marker").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "logs" / "app.log").write_text("日志\n", encoding="utf-8")
    (root / "logs" / "app.log.2026-10-15").write_text("earlier", encoding="utf-8")
    picture = root / "debug" / "hp_marker" / "capture.jpg"
    Image.new("RGB", (12, 10), "red").save(picture)
    metadata = root / "debug" / "hp_marker" / "capture.json"
    metadata.write_text('{"score": 0.99}', encoding="utf-8")
    (root / "settings.yaml").write_text("not included", encoding="utf-8")
    (root / "reports" / "previous.zip").write_bytes(b"not included")
    attachments = []
    for directory, color in (("one", "blue"), ("two", "green")):
        folder = tmp_path / directory
        folder.mkdir()
        attachment = folder / "截图.png"
        Image.new("RGBA", (7, 5), color).save(attachment)
        attachments.append(attachment)
    destination = root / "reports" / "report.zip"
    result = create_diagnostic_archive(root, destination, "问题描述\n复现步骤", tuple(attachments))

    assert result.path == destination.resolve()
    assert result.file_count == 6
    assert result.skipped == ()
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "problem.txt",
            "manifest.json",
            "logs/app.log",
            "logs/app.log.2026-10-15",
            "debug/hp_marker/capture.jpg",
            "debug/hp_marker/capture.json",
            "attachments/001_截图.png",
            "attachments/002_截图.png",
        }
        assert archive.read("problem.txt").decode("utf-8") == "问题描述\n复现步骤"
        assert archive.read("logs/app.log") == (root / "logs" / "app.log").read_bytes()
        assert archive.read("debug/hp_marker/capture.jpg") == picture.read_bytes()
        assert archive.read("debug/hp_marker/capture.json") == metadata.read_bytes()
        for index, attachment in enumerate(attachments, start=1):
            name = f"attachments/{index:03d}_截图.png"
            assert archive.read(name) == attachment.read_bytes()
            assert archive.getinfo(name).compress_type == ZIP_STORED
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["app_version"] == APP_VERSION
        assert len(manifest["files"]) == result.file_count
        assert manifest["skipped_files"] == []
        assert str(tmp_path) not in archive.read("manifest.json").decode("utf-8")
    assert not list(destination.parent.glob(".diagnostics-*"))


def test_empty_diagnostics_can_still_export_a_description(tmp_path: Path) -> None:
    destination = tmp_path / "reports" / "empty.zip"
    result = create_diagnostic_archive(tmp_path / "missing", destination, "")
    assert result.file_count == 0
    with ZipFile(destination) as archive:
        assert set(archive.namelist()) == {"problem.txt", "manifest.json"}


def test_debug_retention_race_is_recorded_without_losing_the_rest(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "debug").mkdir()
    expired = tmp_path / "debug" / "expired.jpg"
    expired.write_bytes(b"old")
    original_write = ZipFile.write

    def write(archive, filename, *args, **kwargs):
        if filename == expired:
            expired.unlink()
        return original_write(archive, filename, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "write", write)
    result = create_diagnostic_archive(tmp_path, tmp_path / "report.zip", "description")
    assert result.skipped == ("debug/expired.jpg",)
    with ZipFile(result.path) as archive:
        assert archive.testzip() is None
        assert "debug/expired.jpg" not in archive.namelist()
        assert json.loads(archive.read("manifest.json"))["skipped_files"] == ["debug/expired.jpg"]


def test_write_failure_preserves_existing_destination_and_removes_partial_zip(tmp_path: Path, monkeypatch):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "app.log").write_text("log", encoding="utf-8")
    destination = tmp_path / "report.zip"
    destination.write_bytes(b"previous archive")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ZipFile, "write", fail)
    with pytest.raises(OSError, match="disk full"):
        create_diagnostic_archive(tmp_path, destination, "description")
    assert destination.read_bytes() == b"previous archive"
    assert not list(tmp_path.glob(".diagnostics-*"))


@pytest.mark.parametrize("missing", [True, False])
def test_invalid_explicit_attachment_fails_instead_of_silently_disappearing(tmp_path: Path, missing):
    attachment = tmp_path / "image.png"
    if not missing:
        attachment.write_bytes(b"not an image")
    destination = tmp_path / "report.zip"
    with pytest.raises((FileNotFoundError, UnidentifiedImageError)):
        create_diagnostic_archive(tmp_path, destination, "description", (attachment,))
    assert not destination.exists()
    assert not list(tmp_path.glob(".diagnostics-*"))


def test_destination_cannot_overwrite_a_collected_source(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    source = tmp_path / "logs" / "app.log"
    source.write_bytes(b"keep")
    with pytest.raises(ValueError, match="overwrite"):
        create_diagnostic_archive(tmp_path, source, "description")
    assert source.read_bytes() == b"keep"
