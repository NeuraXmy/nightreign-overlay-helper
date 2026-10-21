"""Mirror creates Gitee-only tags and remains safe to retry after an upload failure."""

from urllib.error import HTTPError

import pytest
from scripts import sync_gitee_release as sync


@pytest.mark.parametrize("exists", [False, True, None])
@pytest.mark.parametrize("diagnostic", [False, True])
def test_mirror_creates_or_updates_release_and_preserves_matching_attachments(
    tmp_path, monkeypatch, exists, diagnostic
):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "GITEE_TOKEN": "secret",
        "GITEE_REPO": "mirror/repo",
        "GH_TOKEN": "github-token",
        "GITHUB_REPOSITORY": "upstream/repo",
        "RELEASE_TAG": "v1.0.1",
        "DIAGNOSTIC_UPLOAD": str(diagnostic).lower(),
        "GITHUB_RUN_ID": "123",
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
        if method == "GET":
            assert token == "secret"
        if "/releases/tags/" in url:
            if exists is None:
                return None
            if exists is False:
                raise HTTPError(url, 404, "not found", {}, None)
            return {"id": 12}
        if url.endswith("attach_files?per_page=100"):
            return attachments
        if method in ("POST", "PATCH"):
            assert data["tag_name"] == ("v1.0.1-uploadcheck-123" if diagnostic else "v1.0.1")
            assert data["prerelease"] == diagnostic
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


@pytest.mark.parametrize("code,http_code", [(0, 201), (28, 0), (22, 403)])
def test_upload_logs_progress_and_metrics_without_credentials(tmp_path, monkeypatch, capsys, code, http_code):
    import io
    import json

    path = tmp_path / "runtime.zip.001"
    path.write_bytes(b"program")
    credential = "private-token"
    inputs = []

    class Process:
        def __init__(self, command, **kwargs):
            assert credential not in str(command)
            assert "--progress-meter" in command
            inputs.append(io.StringIO())
            self.stdin = inputs[-1]
            self.stderr = io.StringIO(
                " 50 100M 0 0 50 50M 0 1024k 0:01:40 0:00:50 0:00:50 1024k\n"
                f"untrusted error containing {credential}\n"
            )
            kwargs["stdout"].write(
                json.dumps(
                    {
                        "http_code": http_code,
                        "size_upload": 52428800,
                        "speed_upload": 1048576,
                        "time_connect": 0.1,
                        "time_appconnect": 0.2,
                        "time_total": 50.0,
                        "url": "https://example.com/?secret=" + credential,
                    }
                )
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def wait(self):
            return code

    monkeypatch.setattr(sync.subprocess, "Popen", Process)
    if code:
        with pytest.raises(RuntimeError, match=f"curl {code}"):
            sync.upload_attachment("https://example.com/upload", path, credential, timeout=300)
    else:
        sync.upload_attachment("https://example.com/upload", path, credential, timeout=300)
    output = capsys.readouterr().out
    assert "Upload start" in output
    assert "sent=50% (50M)" in output
    assert "average=1024kB/s" in output
    assert f'"http_code": {http_code}' in output
    assert '"size_upload": 52428800' in output
    assert "Upload end" in output
    assert credential not in output
    assert "untrusted error" not in output


def test_diagnostic_cleanup_targets_only_temporary_release(monkeypatch):
    for key, value in {
        "GITEE_TOKEN": "secret",
        "GITEE_REPO": "mirror/repo",
        "RELEASE_TAG": "v1.0.2",
        "GITHUB_RUN_ID": "456",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def api(method, url, data=None, token=""):
        calls.append((method, url))
        if method == "GET":
            assert url.endswith("/tags/v1.0.2-uploadcheck-456")
            return {"id": 789}
        assert method == "DELETE"
        assert url.endswith("/releases/789")
        assert data == {"access_token": "secret"}

    monkeypatch.setattr(sync, "api", api)
    sync.cleanup_diagnostic()
    assert len(calls) == 2
