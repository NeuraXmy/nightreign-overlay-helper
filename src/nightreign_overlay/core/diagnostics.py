"""Build a local diagnostic archive without depending on the UI."""

from __future__ import annotations

import json
import logging
import os
import platform
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from PIL import Image

from nightreign_overlay.core.log import ROOT_LOGGER_NAME
from nightreign_overlay.meta import APP_ID, APP_VERSION


@dataclass(frozen=True)
class DiagnosticArchive:
    path: Path
    file_count: int
    skipped: tuple[str, ...]


def create_diagnostic_archive(
    data_directory: Path, destination: Path, description: str, attachments: tuple[Path, ...] = ()
) -> DiagnosticArchive:
    """Export logs/debug and explicitly selected images; publish only a complete ZIP.

    Diagnostic retention may remove a file during export. Such files are listed in
    manifest.json and the result, while missing or invalid explicit attachments fail
    the export so the user can correct their selection. Original files are untouched.
    """
    for handler in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        handler.flush()
    root = data_directory.resolve()
    destination = destination.resolve()
    sources: list[tuple[Path, str, bool]] = []
    for group in ("logs", "debug"):
        directory = root / group
        if not directory.exists() or directory.is_symlink() or not directory.resolve().is_relative_to(root):
            continue
        for current, directories, files in os.walk(directory, followlinks=False, onerror=_raise_walk_error):
            current_path = Path(current)
            directories[:] = sorted(
                name
                for name in directories
                if not (current_path / name).is_symlink()
                and (current_path / name).resolve().is_relative_to(root)
            )
            for name in sorted(files):
                source = current_path / name
                if source.is_symlink() or not source.resolve().is_relative_to(root):
                    continue
                if source.resolve() == destination:
                    raise ValueError("The archive destination would overwrite a diagnostic source file")
                sources.append((source, source.relative_to(root).as_posix(), False))
    for index, source in enumerate(attachments, start=1):
        if source.resolve() == destination:
            raise ValueError("The archive destination would overwrite an attachment")
        with Image.open(source) as image:
            image.verify()
        sources.append((source, f"attachments/{index:03d}_{source.name}", True))

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".diagnostics-", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    included: list[str] = []
    skipped: list[str] = []
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("problem.txt", description)
            for source, name, required in sources:
                try:
                    # Stream files rather than loading potentially large logs into RAM.
                    # ZipFile.write opens the source before creating its archive member.
                    compression = (
                        ZIP_STORED
                        if source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                        else ZIP_DEFLATED
                    )
                    archive.write(source, name, compress_type=compression)
                except FileNotFoundError:
                    if required:
                        raise
                    skipped.append(name)
                    continue
                included.append(name)
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "schema_version": 1,
                        "app_id": APP_ID,
                        "app_version": APP_VERSION,
                        "created_at": datetime.now().astimezone().isoformat(),
                        "system": platform.system(),
                        "system_release": platform.release(),
                        "architecture": platform.machine(),
                        "python": platform.python_version(),
                        "files": included,
                        "skipped_files": skipped,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return DiagnosticArchive(destination, len(included), tuple(skipped))


def _raise_walk_error(error: OSError) -> None:
    raise error
