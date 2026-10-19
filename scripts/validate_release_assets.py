"""Reject extracted, missing or mismatched ZIPs before creating a GitHub Release."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def validate_assets(directory: Path, tag: str) -> None:
    expected = {
        f"nightreign-overlay-helper-{tag}-windows-x64.zip",
        f"{tag}-sources.zip",
    }
    actual = {path.name for path in directory.iterdir()}
    if actual != expected:
        raise ValueError(f"Expected release ZIPs {sorted(expected)}, got {sorted(actual)}")

    runtime_path = directory / f"nightreign-overlay-helper-{tag}-windows-x64.zip"
    sources_path = directory / f"{tag}-sources.zip"
    with zipfile.ZipFile(runtime_path) as runtime, zipfile.ZipFile(sources_path) as sources:
        for archive in (runtime, sources):
            if bad_file := archive.testzip():
                raise ValueError(f"Corrupt release ZIP entry: {bad_file}")
        prefix = "nightreign-overlay-helper/"
        for name in ("nightreign-overlay-helper.exe", "bin/NightreignP2PHelper.exe", "LICENSE"):
            if not runtime.read(prefix + name):
                raise ValueError(f"Empty runtime file: {name}")
        manifest = sources.read("manifest.json")
        if runtime.read(prefix + "licenses/source-manifest.json") != manifest:
            raise ValueError("Runtime and corresponding source manifests do not match")
        project = json.loads(manifest)["project"]
        with sources.open(project["archive"]) as snapshot:
            if hashlib.file_digest(snapshot, "sha256").hexdigest() != project["sha256"]:
                raise ValueError("Corresponding project source SHA-256 does not match")
    print(f"Verified runtime and corresponding source ZIPs for {tag}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("tag")
    args = parser.parse_args()
    validate_assets(args.directory, args.tag)


if __name__ == "__main__":
    main()
