"""Release filtering, dual-mirror deadlines and atomic download failures."""

import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from nightreign_overlay.core import updates


def release(tag="v1.2.0", source="github"):
    return updates.Release(tag, "notes", source, "https://example.com/runtime.zip", "runtime.zip")


@pytest.mark.parametrize(
    ("tag", "current", "expected"),
    [
        ("v1.0.2", "1.0.1", True),
        ("v1.0.1", "1.0.1", False),
        ("v1.0.1", "1.0.2", False),
        ("v1.0.1", "1.0.1rc1", True),
        ("v1.0.2rc1", "1.0.1", False),
        ("v1.10.0", "1.9.0", True),
    ],
)
def test_version_comparison(tag, current, expected):
    assert updates.is_newer(tag, current) is expected


@pytest.mark.parametrize("failed", ["github", "gitee", None])
def test_both_mirrors_are_probed_and_github_is_preferred(monkeypatch, failed):
    seen = set()

    def fetch(source, deadline):
        seen.add(source)
        if source == failed:
            raise OSError("offline")
        return [release(source=source)]

    monkeypatch.setattr(updates, "fetch_releases", fetch)
    result = updates.check_releases()
    assert seen == {"github", "gitee"}
    assert result[0].source == ("gitee" if failed == "github" else "github")


@pytest.mark.parametrize(
    ("github_tag", "gitee_tag", "expected"),
    [
        ("v1.0.1", "v1.0.2", "gitee"),
        ("v1.0.3", "v1.0.2", "github"),
        ("v1.0.2", "v1.0.2", "github"),
        ("v1.9.0", "v1.10.0", "gitee"),
    ],
)
def test_newest_mirror_is_selected(monkeypatch, github_tag, gitee_tag, expected):
    histories = {
        "github": [release(github_tag, "github"), release("v1.0.1", "github")],
        "gitee": [release(gitee_tag, "gitee"), release("v1.0.1", "gitee")],
    }
    monkeypatch.setattr(updates, "fetch_releases", lambda source, deadline: histories[source])
    assert updates.check_releases() == histories[expected]


def test_stalled_mirror_does_not_exceed_shared_deadline(monkeypatch):
    def fetch(source, deadline):
        if source == "github":
            time.sleep(0.2)
        return [release(source=source)]

    monkeypatch.setattr(updates, "fetch_releases", fetch)
    start = time.monotonic()
    assert updates.check_releases(timeout=0.03)[0].source == "gitee"
    assert time.monotonic() - start < 0.15


def test_both_mirrors_fail(monkeypatch):
    monkeypatch.setattr(updates, "fetch_releases", lambda *args: [])
    with pytest.raises(ConnectionError):
        updates.check_releases()


class Response(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {}


def test_filter_and_sort_releases(monkeypatch):
    items = [
        {"tag_name": tag, "body": tag}
        for tag in ["v1.0.0", "v1.0.1", "v1.10.0", "v1.2.0", "v2.0.0rc1", "legacy"]
    ]
    items.extend([{"tag_name": "v3.0.0", "prerelease": True}, {"tag_name": "v4.0.0", "draft": True}])
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: Response(json.dumps(items).encode()))
    assert [r.tag for r in updates.fetch_releases("github", time.monotonic() + 10)] == [
        "v1.10.0",
        "v1.2.0",
        "v1.0.1",
    ]


def test_gitee_uses_attachment_endpoint(monkeypatch):
    responses = [
        [{"id": 12, "tag_name": "v1.2.0", "assets": []}],
        [
            {
                "name": "nightreign-overlay-helper-v1.2.0-windows-x64.zip",
                "browser_download_url": "https://gitee.com/runtime.zip",
            }
        ],
    ]
    urls = []

    def get(request, **kwargs):
        urls.append(request.full_url)
        return Response(json.dumps(responses.pop(0)).encode())

    monkeypatch.setattr(updates, "urlopen", get)
    result = updates.fetch_releases("gitee", time.monotonic() + 10)
    assert result[0].download_url == "https://gitee.com/runtime.zip"
    assert "/releases/12/attach_files" in urls[-1]


def test_incomplete_download_preserves_existing_file(monkeypatch, tmp_path: Path):
    destination = tmp_path / "update.zip"
    destination.write_bytes(b"original")
    response = Response(b"partial")
    response.headers = {"Content-Length": "100"}
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: response)
    with pytest.raises(OSError, match="Incomplete"):
        updates.download_release(release(), destination)
    assert destination.read_bytes() == b"original"
    assert not destination.with_suffix(".zip.part").exists()


@pytest.mark.parametrize("known_size", [True, False])
def test_successful_download(monkeypatch, tmp_path, known_size):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("test.txt", "test")
    response = Response(buffer.getvalue())
    size = len(buffer.getvalue())
    response.headers = {"Content-Length": str(size)} if known_size else {}
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: response)
    progress = []
    path = updates.download_release(
        release(), tmp_path / "update.zip", lambda done, total: progress.append((done, total))
    )
    assert path.read_bytes() == buffer.getvalue()
    assert progress == [(0, size if known_size else 0), (size, size if known_size else 0)]


def test_github_rate_limit_falls_back_to_feed_within_same_deadline(monkeypatch):
    from urllib.error import HTTPError

    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Arbitrary release title</title>
        <link rel="alternate" href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases/tag/v1.0.1"/>
        <content type="html">&lt;p&gt;Release notes&lt;/p&gt;</content>
      </entry>
      <entry><link rel="alternate"
        href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases/tag/v1.0.0-dev.3"/></entry>
      <entry><link rel="alternate"
        href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases/tag/v0.10.5"/></entry>
    </feed>"""
    requests = []

    def get(request, timeout):
        requests.append((request.full_url, timeout))
        if "api.github.com" in request.full_url:
            raise HTTPError(request.full_url, 403, "rate limit exceeded", {}, None)
        return Response(feed)

    monkeypatch.setattr(updates, "urlopen", get)
    result = updates.fetch_releases("github", time.monotonic() + 10)
    assert [r.tag for r in result] == ["v1.0.1"]
    assert result[0].limited_history
    assert "Release notes" in result[0].body
    assert result[0].download_url.endswith(
        "/releases/download/v1.0.1/nightreign-overlay-helper-v1.0.1-windows-x64.zip"
    )
    assert requests[1][1] <= requests[0][1]
    assert not updates.is_newer(result[0].tag, "1.0.1")


def test_mirror_errors_preserve_http_status_and_source(monkeypatch):
    from urllib.error import HTTPError

    def fetch(source, deadline):
        raise HTTPError("https://example.com", 403 if source == "github" else 404, "unavailable", {}, None)

    monkeypatch.setattr(updates, "fetch_releases", fetch)
    with pytest.raises(ConnectionError) as error:
        updates.check_releases()
    assert "Github: HTTP Error 403" in str(error.value)
    assert "Gitee: HTTP Error 404" in str(error.value)


@pytest.mark.parametrize("corruption", [None, "part", "full", "missing", "network"])
def test_split_download_merges_verifies_and_preserves_existing_file(monkeypatch, tmp_path, corruption):
    from scripts.sync_gitee_release import prepare_runtime

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app.txt", "application" * 30)
    filename = "runtime.zip"
    original = tmp_path / filename
    original.write_bytes(buffer.getvalue())
    files = prepare_runtime(original, part_size=100)
    payloads = {"https://gitee.com/" + path.name: path.read_bytes() for path in files}
    urls = tuple((path.name, "https://gitee.com/" + path.name) for path in files[:-1])
    manifest_url = "https://gitee.com/" + files[-1].name
    if corruption == "part":
        payloads[urls[0][1]] = b"x" * len(payloads[urls[0][1]])
    elif corruption == "full":
        manifest = json.loads(payloads[manifest_url])
        manifest["sha256"] = "0" * 64
        payloads[manifest_url] = json.dumps(manifest).encode()
    elif corruption == "missing":
        urls = urls[1:]

    def get(request, **kwargs):
        if corruption == "network" and request.full_url.endswith(".002"):
            raise OSError("connection lost")
        return Response(payloads[request.full_url])

    monkeypatch.setattr(updates, "urlopen", get)
    candidate = updates.Release(
        "v1.0.1", "notes", "gitee", manifest_url, filename, split_manifest=True, attachments=urls
    )
    destination = tmp_path / "download.zip"
    destination.write_bytes(b"existing")
    if corruption:
        with pytest.raises((ValueError, OSError)):
            updates.download_release(candidate, destination)
        assert destination.read_bytes() == b"existing"
    else:
        progress = []
        assert (
            updates.download_release(
                candidate, destination, lambda done, total: progress.append((done, total))
            )
            == destination
        )
        assert destination.read_bytes() == buffer.getvalue()
        size = len(buffer.getvalue())
        assert progress[0] == (0, size)
        assert progress[-1] == (size, size)
        assert len(progress) == len(files)
        assert all(total == size for _, total in progress)
        assert [done for done, _ in progress] == sorted(done for done, _ in progress)
    assert not destination.with_name(destination.name + ".part").exists()


def test_gitee_detects_split_manifest_without_extra_metadata_request(monkeypatch):
    responses = [
        [{"id": 12, "tag_name": "v1.2.0", "assets": []}],
        [
            {
                "name": "nightreign-overlay-helper-v1.2.0-windows-x64.zip.manifest.json",
                "browser_download_url": "https://gitee.com/manifest.json",
            },
            {
                "name": "nightreign-overlay-helper-v1.2.0-windows-x64.zip.001",
                "browser_download_url": "https://gitee.com/runtime.zip.001",
            },
        ],
    ]
    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: Response(json.dumps(responses.pop(0)).encode()))
    result = updates.fetch_releases("gitee", time.monotonic() + 10)[0]
    assert result.split_manifest
    assert result.download_url == "https://gitee.com/manifest.json"
    assert len(result.attachments) == 2


@pytest.mark.parametrize("split", [False, True])
def test_cancel_download_cleans_partial_and_stops_next_request(monkeypatch, tmp_path, split):
    from scripts.sync_gitee_release import prepare_runtime

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app.txt", "application" * 30)
    original = tmp_path / "runtime.zip"
    original.write_bytes(buffer.getvalue())
    files = prepare_runtime(original, part_size=100) if split else [original]
    payloads = {"https://example.com/" + p.name: p.read_bytes() for p in files}
    requested = []

    def get(request, **kwargs):
        requested.append(request.full_url)
        return Response(payloads[request.full_url])

    monkeypatch.setattr(updates, "urlopen", get)
    candidate = updates.Release(
        "v1.0.2",
        "notes",
        "gitee",
        "https://example.com/" + files[-1].name,
        "runtime.zip",
        split_manifest=split,
        attachments=tuple((p.name, "https://example.com/" + p.name) for p in files[:-1]),
    )
    destination = tmp_path / "download.zip"
    destination.write_bytes(b"existing")
    cancellation = updates.DownloadCancellation()

    def progress(done, total):
        if done:
            cancellation.cancel()

    with pytest.raises(updates.DownloadCancelledError):
        updates.download_release(candidate, destination, progress, cancellation)
    assert destination.read_bytes() == b"existing"
    assert not destination.with_name(destination.name + ".part").exists()
    assert len(requested) == (2 if split else 1)


def test_cancellation_interrupts_blocked_network_read(monkeypatch):
    import socket
    import threading
    from types import SimpleNamespace

    reader, writer = socket.socketpair()
    entered = threading.Event()
    stopped = threading.Event()
    cancellation = updates.DownloadCancellation()

    class BlockedResponse:
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=reader))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            reader.close()

    monkeypatch.setattr(updates, "urlopen", lambda *a, **k: BlockedResponse())

    def work():
        try:
            with cancellation.open(updates.Request("https://example.com/file")):
                entered.set()
                reader.recv(1024)
                cancellation.check()
        except updates.DownloadCancelledError:
            stopped.set()

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        cancellation.cancel()
        assert stopped.wait(1)
        worker.join(1)
        assert not worker.is_alive()
    finally:
        writer.close()
