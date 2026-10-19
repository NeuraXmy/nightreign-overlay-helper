"""Collect the named licenses and exact source archives; fail closed on drift."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request
import zipfile
from importlib.metadata import distribution
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = {
    "pyqt6": "PyQt6-LICENSE.txt",
    "pyqt6-fluent-widgets": "PyQt6-Fluent-Widgets-LICENSE.txt",
}
LEGAL_FILES = (
    "AGPL-3.0.txt",
    *DEPENDENCIES.values(),
    "THIRD-PARTY-NOTICES.md",
    "source-origins.json",
)
MIT_FILES = ("SteamP2PInfo-LICENSE.txt", "Steamworks.NET-LICENSE.txt", "TraceEvent-LICENSE.txt")


def locked_dependencies(root: Path) -> dict[str, dict]:
    packages = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))["package"]
    result = {}
    for name in DEPENDENCIES:
        matches = [package for package in packages if package["name"] == name]
        if len(matches) != 1 or "sdist" not in matches[0]:
            raise ValueError(f"Expected one locked source distribution for {name}")
        result[name] = matches[0]
    return result


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root).decode("utf-8").strip()


def check_tree(root: Path) -> None:
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Release builds require a clean Git worktree; commit source changes first")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_hash(path: Path, expected: str) -> None:
    if sha256(path) != expected:
        raise ValueError(f"Source archive SHA-256 mismatch: {path.name}")


def download_source(url: str, archive: Path, expected: str) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    verify_hash(archive, expected)


def verify_fluent_resource_sources(sdist: Path, upstream: Path) -> None:
    """The sdist contains generated resource.py, so also preserve its editable inputs."""
    with tarfile.open(sdist) as package, zipfile.ZipFile(upstream) as repository:
        prefix = repository.namelist()[0].split("/", 1)[0] + "/"
        if not any(name.endswith(".qrc") for name in repository.namelist()):
            raise ValueError("Fluent Widgets repository archive lacks editable Qt resources")
        count = 0
        for member in package.getmembers():
            relative = member.name.split("/", 1)[-1]
            if not relative.startswith("qfluentwidgets/") or not relative.endswith(".py"):
                continue
            stream = package.extractfile(member)
            if stream is None:
                raise ValueError(f"Missing Fluent Widgets source: {relative}")
            with stream:
                original = stream.read().replace(b"\r\n", b"\n")
            candidate = repository.read(prefix + relative).replace(b"\r\n", b"\n")
            if original != candidate:
                raise ValueError(f"Fluent Widgets upstream source does not match sdist: {relative}")
            count += 1
        if not count:
            raise ValueError("Fluent Widgets sdist has no Python source")


def source_directory(bundle: Path) -> Path:
    return bundle.parent / "release-sources"


def release_label(root: Path) -> str:
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        return os.environ["GITHUB_REF_NAME"]
    revision = git(root, "rev-parse", "--short=7", "HEAD")
    return f"manual-dev-{revision}-{os.environ.get('GITHUB_RUN_NUMBER', 'local')}"


def source_notice(root: Path) -> str:
    legal = root / "src/nightreign_overlay/resources/licenses"
    archive = f"{release_label(root)}-sources.zip"
    location = f"../{archive}"
    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        repository = os.environ.get("GITHUB_REPOSITORY", "NeuraXmy/nightreign-overlay-helper")
        tag = quote(os.environ["GITHUB_REF_NAME"], safe="")
        location = f"https://github.com/{repository}/releases/download/{tag}/{quote(archive, safe='')}"
    return (legal / "SOURCE.md").read_text(encoding="utf-8") + (
        f"\n## This build / 本次构建\n\n"
        f"- Commit: `{git(root, 'rev-parse', 'HEAD')}`\n"
        f"- Corresponding source / 对应源码: [{archive}]({location})\n"
    )


def prepare(root: Path, bundle: Path) -> None:
    check_tree(root)
    packages = locked_dependencies(root)
    legal = root / "src/nightreign_overlay/resources/licenses"
    for name, filename in DEPENDENCIES.items():
        installed = distribution(name)
        if installed.version != packages[name]["version"]:
            raise ValueError(f"Installed {name} does not match uv.lock")
        license_file = next(entry for entry in installed.files or () if str(entry).endswith("/LICENSE"))
        actual = installed.locate_file(license_file).read_text(encoding="utf-8").split()
        if actual != (legal / filename).read_text(encoding="utf-8").split():
            raise ValueError(f"Review and update the bundled license for {name}")
    if (legal / "AGPL-3.0.txt").read_bytes() != (root / "LICENSE").read_bytes():
        raise ValueError("Bundled AGPL text differs from project LICENSE")
    if (legal / "SteamP2PInfo-LICENSE.txt").read_bytes() != (
        root / "native/licenses/SteamP2PInfo-LICENSE.txt"
    ).read_bytes():
        raise ValueError("Offline SteamP2PInfo license differs from native license")

    (bundle / "licenses").mkdir(parents=True, exist_ok=True)
    for filename in LEGAL_FILES:
        shutil.copyfile(legal / filename, bundle / "licenses" / filename)
    (bundle / "SOURCE.md").write_text(source_notice(root), encoding="utf-8")
    shutil.copyfile(root / "LICENSE", bundle / "LICENSE")
    third_party = bundle / "third-party"
    third_party.mkdir(exist_ok=True)
    shutil.copyfile(root / "native/THIRD-PARTY-NOTICES.txt", third_party / "THIRD-PARTY-NOTICES.txt")
    shutil.copytree(root / "native/licenses", third_party / "licenses", dirs_exist_ok=True)

    # Remove the previous layout from incremental local builds as well.
    legacy_sources = bundle / "source"
    if legacy_sources.exists():
        shutil.rmtree(legacy_sources)
    sources = source_directory(bundle)
    if sources.exists():
        shutil.rmtree(sources)
    sources.mkdir(parents=True)
    revision = git(root, "rev-parse", "HEAD")
    snapshot = sources / "nightreign-overlay-helper-source.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", f"--output={snapshot.resolve()}", revision],
        cwd=root,
        check=True,
    )
    manifest = {
        "project": {"commit": revision, "archive": snapshot.name, "sha256": sha256(snapshot)},
        "dependencies": {},
    }
    for name, package in packages.items():
        sdist = package["sdist"]
        filename = Path(urlparse(sdist["url"]).path).name
        archive = sources / filename
        algorithm, expected = sdist["hash"].split(":", 1)
        if algorithm != "sha256":
            raise ValueError(f"Unsupported source hash algorithm: {algorithm}")
        # uv.lock supplies the exact source URL and hash; never substitute a moving branch.
        download_source(sdist["url"], archive, expected)
        manifest["dependencies"][name] = {
            "version": package["version"],
            "url": sdist["url"],
            "archive": filename,
            "sha256": expected,
        }
    supplements = json.loads((legal / "source-origins.json").read_text(encoding="utf-8"))
    for name, record in supplements.items():
        if record["version"] != packages[name]["version"]:
            raise ValueError(f"Review and pin the upstream resource source for {name}")
        download_source(record["url"], sources / record["archive"], record["sha256"])
    manifest["supplements"] = supplements
    (sources / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(sources / "manifest.json", bundle / "licenses/source-manifest.json")
    shutil.copyfile(bundle / "SOURCE.md", sources / "SOURCE.md")
    shutil.copyfile(root / "LICENSE", sources / "LICENSE")
    check_tree(root)
    if git(root, "rev-parse", "HEAD") != revision:
        raise ValueError("Git revision changed while preparing release sources")
    check_bundle(root, bundle)


def check_bundle(root: Path, bundle: Path) -> None:
    legal = root / "src/nightreign_overlay/resources/licenses"
    required = {
        **{f"licenses/{name}": legal / name for name in LEGAL_FILES},
        **{f"third-party/licenses/{name}": root / "native/licenses" / name for name in MIT_FILES},
        "third-party/THIRD-PARTY-NOTICES.txt": root / "native/THIRD-PARTY-NOTICES.txt",
        "LICENSE": root / "LICENSE",
    }
    for relative, original in required.items():
        if (bundle / relative).read_bytes() != original.read_bytes():
            raise ValueError(f"Missing or incorrect release license/notice: {relative}")
    if (bundle / "source").exists():
        raise ValueError("Runtime bundle must not contain source archives")
    if (bundle / "SOURCE.md").read_text(encoding="utf-8") != source_notice(root):
        raise ValueError("Runtime source download notice does not match this build")
    sources = source_directory(bundle)
    if (sources / "SOURCE.md").read_bytes() != (bundle / "SOURCE.md").read_bytes():
        raise ValueError("Source archive download notice does not match runtime")
    if (sources / "LICENSE").read_bytes() != (root / "LICENSE").read_bytes():
        raise ValueError("Source archive license does not match project")
    if (bundle / "licenses/source-manifest.json").read_bytes() != (sources / "manifest.json").read_bytes():
        raise ValueError("Runtime source manifest does not match corresponding source")
    manifest = json.loads((sources / "manifest.json").read_text(encoding="utf-8"))
    packages = locked_dependencies(root)
    if set(manifest["dependencies"]) != set(packages):
        raise ValueError("Release source dependency list does not match uv.lock")
    supplements = json.loads((legal / "source-origins.json").read_text(encoding="utf-8"))
    if manifest["supplements"] != supplements:
        raise ValueError("Release resource source metadata does not match pinned origins")
    for name, record in supplements.items():
        if record["version"] != packages[name]["version"]:
            raise ValueError(f"Upstream resource source version does not match uv.lock: {name}")
    for name, package in packages.items():
        record = manifest["dependencies"][name]
        if (
            record["version"] != package["version"]
            or record["url"] != package["sdist"]["url"]
            or f"sha256:{record['sha256']}" != package["sdist"]["hash"]
        ):
            raise ValueError(f"Release source metadata does not match uv.lock: {name}")
    if manifest["project"]["commit"] != git(root, "rev-parse", "HEAD"):
        raise ValueError("Release source commit does not match the checkout")
    for record in [manifest["project"], *manifest["dependencies"].values(), *supplements.values()]:
        if Path(record["archive"]).name != record["archive"]:
            raise ValueError("Source archive must be a plain filename")
        verify_hash(sources / record["archive"], record["sha256"])
    verify_fluent_resource_sources(
        sources / manifest["dependencies"]["pyqt6-fluent-widgets"]["archive"],
        sources / supplements["pyqt6-fluent-widgets"]["archive"],
    )
    with zipfile.ZipFile(sources / manifest["project"]["archive"]) as snapshot:
        for filename in ("LICENSE", "uv.lock", "build.bat", "scripts/prepare_release_licenses.py"):
            if snapshot.read(filename).replace(b"\r\n", b"\n") != (root / filename).read_bytes().replace(
                b"\r\n", b"\n"
            ):
                raise ValueError(f"Release source snapshot mismatch: {filename}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify an existing bundle without networking")
    mode.add_argument("--check-tree", action="store_true", help="Reject uncommitted release source")
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/nightreign-overlay-helper")
    args = parser.parse_args()
    if args.check_tree:
        check_tree(ROOT)
    elif args.check:
        check_bundle(ROOT, args.bundle)
    else:
        prepare(ROOT, args.bundle)


if __name__ == "__main__":
    main()
