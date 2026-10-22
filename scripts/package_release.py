"""Create separate runtime and corresponding-source ZIPs from a verified build."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

from scripts.prepare_release_licenses import ROOT, check_bundle, release_label, source_directory

from nightreign_overlay.plugins.audio.defaults import BUNDLED_CUES, BUNDLED_LOOP_AUDIO

REQUIRED_RUNTIME_FILES = (
    "nightreign-overlay-helper.exe",
    "_internal/nightreign_overlay/plugins/capture/native/MaaWin32Screencap.dll",
    "_internal/nightreign_overlay/plugins/map_detect/data/poi_cnn/epoch-42.onnx",
    "_internal/nightreign_overlay/plugins/hp_marker/data/material_v1.onnx",
    "_internal/nightreign_overlay/plugins/hp_marker/data/cap_v1.onnx",
    "bin/NightreignP2PHelper.exe",
    "bin/amd64/KernelTraceControl.dll",
    "bin/amd64/msdia140.dll",
    "README.md",
    *(f"_internal/nightreign_overlay/plugins/audio/sounds/{cue.filename}" for cue in BUNDLED_CUES.values()),
    *(
        f"_internal/nightreign_overlay/plugins/audio/sounds/{filename}"
        for filename in BUNDLED_LOOP_AUDIO.values()
    ),
)


def create_zip(directory: Path, destination: Path, *, include_directory: bool) -> None:
    base = directory.parent if include_directory else directory
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(base).as_posix())


def package(root: Path, bundle: Path) -> tuple[Path, Path]:
    check_bundle(root, bundle)
    for name in REQUIRED_RUNTIME_FILES:
        if not (bundle / name).is_file():
            raise FileNotFoundError(f"Missing bundle file: {name}")
    label = release_label(root)
    # Labels become file names; reject path separators and Windows-invalid names.
    if not label or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in label
    ):
        raise ValueError(f"Unsupported release label: {label!r}")
    runtime = bundle.parent / f"nightreign-overlay-helper-{label}-windows-x64.zip"
    sources = bundle.parent / f"{label}-sources.zip"
    create_zip(bundle, runtime, include_directory=True)
    create_zip(source_directory(bundle), sources, include_directory=False)
    return runtime, sources


def main() -> None:
    runtime, sources = package(ROOT, ROOT / "dist/nightreign-overlay-helper")
    for path in (runtime, sources):
        print(f"Created {path.name}: {path.stat().st_size / 1024**2:.2f} MiB")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"name={runtime.stem}\npath={runtime}\nsources-path={sources}\n")


if __name__ == "__main__":
    main()
