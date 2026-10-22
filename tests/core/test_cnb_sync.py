"""CNB cloud synchronization verifies identical upstream and published bytes."""

import hashlib
import json

import pytest
from scripts import sync_cnb_release as sync


@pytest.mark.parametrize("failure", [None, "digest", "published_hash"])
def test_cloud_sync_verifies_upstream_before_upload_and_verifies_publication(tmp_path, monkeypatch, failure):
    monkeypatch.chdir(tmp_path)
    payload = b"upstream runtime"
    digest = hashlib.sha256(payload).hexdigest()
    filename = "nightreign-overlay-helper-v1.0.2-windows-x64.zip"
    upstream = {
        "tag_name": "v1.0.2",
        "body": "User-facing release notes",
        "assets": [
            {
                "name": filename,
                "size": len(payload),
                "digest": "sha256:" + digest,
                "browser_download_url": f"https://github.com/owner/repo/releases/download/v1.0.2/{filename}",
            }
        ],
    }
    for key, value in {
        "RELEASE_TAG": "v1.0.2",
        "CNB_TOKEN": "private-token",
        "CNB_REPO": "mirror/repo",
        "GITHUB_REPOSITORY": "owner/repo",
        "UPSTREAM_RELEASE_JSON": json.dumps(upstream),
    }.items():
        monkeypatch.setenv(key, value)
    calls = []
    base = "https://api.cnb.cool/mirror/repo/-/releases"

    def api(method, url, token="", data=None):
        assert token == "private-token"
        calls.append((method, url))
        if url.endswith("/tags/v1.0.2"):
            if len(calls) == 1:
                return {"id": "123", "assets": None}
            return {
                "assets": [
                    {
                        "name": filename,
                        "size": len(payload),
                        "hash_value": "bad" if failure == "published_hash" else digest,
                    }
                ]
            }
        if url.endswith("/asset-upload-url"):
            assert data["size"] == len(payload)
            return {
                "upload_url": "https://storage.example/upload?signature=secret",
                "verify_url": base + "/123/asset-upload-confirmation/token/asset",
            }
        if method == "PATCH":
            assert data["body"] == upstream["body"]
        return None

    transfers = []

    def transfer(url, path, *, upload=False):
        transfers.append(upload)
        if not upload:
            path.write_bytes(b"wrong" if failure == "digest" else payload)

    monkeypatch.setattr(sync, "api", api)
    monkeypatch.setattr(sync, "transfer", transfer)
    if failure:
        with pytest.raises(ValueError, match=r"mismatch|verification"):
            sync.sync()
    else:
        sync.sync()
    if failure == "digest":
        assert not calls
        assert transfers == [False]
    else:
        assert transfers == [False, True]
        assert any("asset-upload-confirmation" in url for _, url in calls)


def test_transfer_logs_numeric_metrics_without_signed_url(tmp_path, monkeypatch, capsys):
    import subprocess

    def run(args, **kwargs):
        assert "signature" not in str(args)
        assert "signature=secret" in kwargs["input"]
        return subprocess.CompletedProcess(args, 0, "200 200 0 100 0 2.0", "")

    monkeypatch.setattr(sync.subprocess, "run", run)
    sync.transfer("https://storage.example/file?signature=secret", tmp_path / "runtime.zip")
    output = capsys.readouterr().out
    assert "200 200 0 100 0 2.0" in output
    assert "signature" not in output


def test_trigger_supplies_current_script_and_waits_for_completion(monkeypatch):
    from scripts import trigger_cnb_sync as trigger

    for key, value in {
        "RELEASE_TAG": "v1.0.2",
        "GITHUB_REPOSITORY": "owner/repo",
        "GH_TOKEN": "github-secret",
        "CNB_TOKEN": "cnb-secret",
    }.items():
        monkeypatch.setenv(key, value)
    statuses = iter(["running", "success"])
    calls = []

    def api(method, url, token="", data=None):
        calls.append(url)
        if "api.github.com" in url:
            assert token == "github-secret"
            return {"tag_name": "v1.0.2", "body": "notes", "assets": []}
        assert token == "cnb-secret"
        if url.endswith("/start"):
            config = json.loads(data["config"])
            script = config["main"]["api_trigger"][0]["stages"][0]["script"]
            assert "hashlib.file_digest" in script
            assert "secret" not in data["config"]
            metadata = json.loads(data["env"]["UPSTREAM_RELEASE_JSON"])
            assert metadata["tag_name"] == "v1.0.2"
            return {"success": True, "sn": "test-build"}
        return {"status": next(statuses)}

    monkeypatch.setattr(trigger, "api", api)
    monkeypatch.setattr(trigger.time, "sleep", lambda _: None)
    trigger.trigger()
    assert len(calls) == 4
