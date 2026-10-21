"""Mirror creates Gitee-only tags and remains safe to retry after an upload failure."""

from urllib.error import HTTPError

import pytest
from scripts import sync_gitee_release as sync


@pytest.mark.parametrize("exists", [False, True])
def test_mirror_creates_or_updates_release_and_preserves_matching_attachments(tmp_path, monkeypatch, exists):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "GITEE_TOKEN": "secret",
        "GITEE_REPO": "mirror/repo",
        "GH_TOKEN": "github-token",
        "GITHUB_REPOSITORY": "upstream/repo",
        "RELEASE_TAG": "v1.0.1",
    }.items():
        monkeypatch.setenv(key, value)
    directory = tmp_path / "release"
    directory.mkdir()
    names = ["nightreign-overlay-helper-v1.0.1-windows-x64.zip"]
    for name in names:
        (directory / name).write_bytes(b"zip")
    attachments = [{"name": name, "size": 3, "id": i} for i, name in enumerate(names)]
    calls = []

    def api(method, url, data=None, token=""):
        calls.append((method, url, data))
        if "api.github.com" in url:
            return {"name": "Release", "body": "Notes", "prerelease": False, "assets": attachments}
        if "/releases/tags/" in url:
            if not exists:
                raise HTTPError(url, 404, "not found", {}, None)
            return {"id": 12}
        if url.endswith("attach_files?per_page=100"):
            return attachments
        if method in ("POST", "PATCH"):
            assert data["body"].startswith("Notes")
            assert (
                "https://github.com/upstream/repo/releases/download/v1.0.1/v1.0.1-sources.zip" in data["body"]
            )
            assert data["access_token"] == "secret"
            if method == "POST":
                assert data["target_commitish"] == "main"
            return {"id": 12}
        return {"default_branch": "main"}

    monkeypatch.setattr(sync, "api", api)
    monkeypatch.setattr(
        sync.subprocess, "run", lambda *a, **k: pytest.fail("Matching assets must not upload")
    )
    sync.sync()
    assert any(method == ("PATCH" if exists else "POST") for method, _, _ in calls)
    assert all("secret" not in url for _, url, _ in calls)


def test_split_runtime_manifest_restores_original_and_hashes(tmp_path):
    import hashlib
    import json

    path = tmp_path / "runtime.zip"
    original = b"original bytes" * 10
    path.write_bytes(original)
    files = sync.prepare_runtime(path, part_size=31)
    manifest = json.loads(files[-1].read_text())
    assert b"".join(part.read_bytes() for part in files[:-1]) == original
    assert all(part.stat().st_size <= 31 for part in files[:-1])
    assert manifest["sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["size"] == len(original)
    for path, part in zip(files[:-1], manifest["parts"], strict=True):
        assert path.name == part["name"]
        assert path.stat().st_size == part["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == part["sha256"]
