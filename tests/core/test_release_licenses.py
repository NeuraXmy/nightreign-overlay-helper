"""Release validation must reject missing legal materials and mismatched source."""

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import zipfile

import pytest
from scripts import prepare_release_licenses as release


@pytest.fixture
def release_checkout(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    for name in ("LICENSE", "uv.lock", "build.bat", "scripts/prepare_release_licenses.py"):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release.ROOT / name, target)
    for name in ("src/nightreign_overlay/resources/licenses", "native/licenses"):
        shutil.copytree(release.ROOT / name, root / name)
    shutil.copyfile(release.ROOT / "native/THIRD-PARTY-NOTICES.txt", root / "native/THIRD-PARTY-NOTICES.txt")
    (root / ".gitignore").write_text("dist/\n")
    module = b'__version__ = "test"\n'
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("package/qfluentwidgets/__init__.py")
        member.size = len(module)
        archive.addfile(member, io.BytesIO(module))
    payload = tar_buffer.getvalue()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("upstream/qfluentwidgets/__init__.py", module)
        archive.writestr("upstream/qfluentwidgets/_rc/resource.qrc", "<RCC/>")
    upstream = zip_buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    packages = release.locked_dependencies(root)
    # Keep real dependency versions/licenses, but supply small offline test archives.
    lock = "\n".join(
        f'[[package]]\nname = "{name}"\nversion = "{package["version"]}"\n'
        f'sdist = {{ url = "https://example.test/{name}.tar.gz", hash = "sha256:{digest}" }}\n'
        for name, package in packages.items()
    )
    (root / "uv.lock").write_text(lock)
    origins = root / "src/nightreign_overlay/resources/licenses/source-origins.json"
    records = json.loads(origins.read_text())
    records["pyqt6-fluent-widgets"].update(
        url="https://example.test/upstream.zip", sha256=hashlib.sha256(upstream).hexdigest()
    )
    origins.write_text(json.dumps(records))
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Release Test",
            "-c",
            "user.email=test@example.test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Test source snapshot",
        ],
        cwd=root,
        check=True,
    )
    monkeypatch.setattr(
        release.urllib.request,
        "urlopen",
        lambda url, **kwargs: io.BytesIO(upstream if url.endswith("upstream.zip") else payload),
    )
    return root, root / "dist/app"


def test_bundle_includes_verified_source_and_full_licenses(release_checkout):
    root, bundle = release_checkout
    release.prepare(root, bundle)
    release.check_bundle(root, bundle)
    manifest = json.loads((bundle / "source/manifest.json").read_text())
    assert manifest["project"]["commit"] == release.git(root, "rev-parse", "HEAD")
    assert set(manifest["dependencies"]) == set(release.DEPENDENCIES)


@pytest.mark.parametrize(
    "filename", ["licenses/PyQt6-LICENSE.txt", "third-party/licenses/SteamP2PInfo-LICENSE.txt"]
)
def test_missing_license_blocks_release(release_checkout, filename):
    root, bundle = release_checkout
    release.prepare(root, bundle)
    (bundle / filename).unlink()
    with pytest.raises(FileNotFoundError):
        release.check_bundle(root, bundle)


def test_corrupted_dependency_source_blocks_release(release_checkout):
    root, bundle = release_checkout
    release.prepare(root, bundle)
    (bundle / "source/pyqt6.tar.gz").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        release.check_bundle(root, bundle)


def test_bad_download_cannot_become_a_release(release_checkout, monkeypatch):
    root, bundle = release_checkout
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"wrong"))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        release.prepare(root, bundle)


def test_uncommitted_source_cannot_be_paired_with_old_snapshot(release_checkout):
    root, bundle = release_checkout
    (root / "build.bat").write_text("modified build script")
    with pytest.raises(ValueError, match="clean Git worktree"):
        release.prepare(root, bundle)


def test_manifest_cannot_substitute_another_dependency_version(release_checkout):
    root, bundle = release_checkout
    release.prepare(root, bundle)
    path = bundle / "source/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["dependencies"]["pyqt6"]["version"] = "0.0.0"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=r"does not match uv\.lock"):
        release.check_bundle(root, bundle)


def test_unrelated_upstream_source_cannot_replace_resource_inputs(tmp_path):
    sdist = tmp_path / "source.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo("package/qfluentwidgets/__init__.py")
        member.size = 8
        archive.addfile(member, io.BytesIO(b"original"))
    upstream = tmp_path / "upstream.zip"
    with zipfile.ZipFile(upstream, "w") as archive:
        archive.writestr("repo/qfluentwidgets/__init__.py", b"modified")
        archive.writestr("repo/resources/resource.qrc", "<RCC/>")
    with pytest.raises(ValueError, match="does not match sdist"):
        release.verify_fluent_resource_sources(sdist, upstream)
