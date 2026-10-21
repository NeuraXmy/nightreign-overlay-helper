"""Public release metadata and downloads; no GUI or credentials in the client."""

from __future__ import annotations

import hashlib
import json
import re
import socket
import threading
import time
import zipfile
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from nightreign_overlay.core.log import get_logger
from nightreign_overlay.meta import GITEE_REPO, GITHUB_REPO

CHECK_TIMEOUT = 10.0
REPOSITORIES = {"github": GITHUB_REPO, "gitee": GITEE_REPO}
log = get_logger(__name__)


def stable_version(tag: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(map(int, match.groups())) if match else None


def is_newer(tag: str, current: str) -> bool:
    target = stable_version(tag)
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)(.*)", current)
    if target is None or match is None:
        return False
    installed = tuple(map(int, match.groups()[:3]))
    prerelease = re.match(r"[-.]?(?:dev|alpha|beta|preview|pre|rc|a|b)", match.group(4), re.IGNORECASE)
    return target > installed or (target == installed and prerelease is not None)


@dataclass(frozen=True)
class Release:
    tag: str
    body: str
    source: str
    download_url: str
    filename: str
    limited_history: bool = False
    body_is_html: bool = False
    split_manifest: bool = False
    attachments: tuple[tuple[str, str], ...] = ()

    @property
    def page_url(self) -> str:
        return f"https://{self.source}.com/{REPOSITORIES[self.source]}/releases"


def fetch_github_feed(deadline: float) -> list[Release]:
    """The public Atom feed remains available when the anonymous API is rate limited.

    GitHub exposes only recent releases in this feed, so tell the history UI that
    it must also offer the full release history link.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Release check timed out")
    request = Request(
        f"https://github.com/{GITHUB_REPO}/releases.atom",
        headers={"User-Agent": "NightreignOverlayHelper", "Accept": "application/atom+xml"},
    )
    with urlopen(request, timeout=remaining) as response:
        payload = response.read(8 * 1024 * 1024 + 1)
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("Release metadata too large")
    root = ElementTree.fromstring(payload)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    releases = []
    for entry in root.findall("atom:entry", namespace):
        # GitHub titles can be arbitrary; the stable release tag is in its link.
        link = entry.find("atom:link[@rel='alternate']", namespace)
        if link is None:
            continue
        prefix = f"https://github.com/{GITHUB_REPO}/releases/tag/"
        url = link.get("href", "")
        if not url.startswith(prefix):
            continue
        tag = url.removeprefix(prefix)
        version = stable_version(tag)
        if version is None or version < (1, 0, 1):
            continue
        filename = f"nightreign-overlay-helper-{tag}-windows-x64.zip"
        body = entry.findtext("atom:content", "", namespace)
        download = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/{filename}"
        releases.append(
            Release(tag, body, "github", download, filename, limited_history=True, body_is_html=True)
        )
    return sorted(releases, key=lambda r: stable_version(r.tag), reverse=True)


def fetch_releases(source: str, deadline: float) -> list[Release]:
    try:
        return _fetch_api_releases(source, deadline)
    except HTTPError as error:
        if source != "github" or error.code not in (403, 429):
            raise
        log.warning("GitHub API returned HTTP %s; trying the public release feed", error.code)
        return fetch_github_feed(deadline)


def _fetch_api_releases(source: str, deadline: float) -> list[Release]:
    repo = REPOSITORIES[source]
    base = "https://api.github.com/repos" if source == "github" else "https://gitee.com/api/v5/repos"
    releases = []
    page = 1
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Release check timed out")
        request = Request(
            f"{base}/{repo}/releases?per_page=100&page={page}",
            headers={"User-Agent": "NightreignOverlayHelper", "Accept": "application/json"},
        )
        with urlopen(request, timeout=remaining) as response:
            # Bound metadata memory use as well as request duration.
            payload = response.read(8 * 1024 * 1024 + 1)
        if len(payload) > 8 * 1024 * 1024:
            raise ValueError("Release metadata too large")
        items = json.loads(payload)
        if not isinstance(items, list):
            raise ValueError("Invalid release response")
        for item in items:
            tag = item.get("tag_name", "")
            version = stable_version(tag)
            if item.get("draft") or item.get("prerelease") or version is None or version < (1, 0, 1):
                continue
            filename = f"nightreign-overlay-helper-{tag}-windows-x64.zip"
            assets = item.get("assets") or {}
            assets = assets if isinstance(assets, list) else assets.get("links", [])
            url = next(
                (
                    a.get("browser_download_url") or a.get("direct_asset_url") or a.get("url", "")
                    for a in assets
                    if isinstance(a, dict) and a.get("name") == filename
                ),
                "",
            )
            if url and not url.startswith("https://"):
                url = ""
            releases.append(Release(tag, item.get("body") or "", source, url, filename))
        if len(items) < 100:
            break
        page += 1
    releases.sort(key=lambda r: stable_version(r.tag), reverse=True)
    if source == "gitee" and releases and not releases[0].download_url:
        latest = releases[0]
        # Gitee's release list does not consistently embed attachment objects.
        item = next(item for item in items if item.get("tag_name") == latest.tag) if page == 1 else None
        if item is None:
            request = Request(f"{base}/{repo}/releases/tags/{latest.tag}")
            with urlopen(request, timeout=max(0.01, deadline - time.monotonic())) as response:
                item = json.load(response)
        request = Request(f"{base}/{repo}/releases/{item['id']}/attach_files?per_page=100")
        with urlopen(request, timeout=max(0.01, deadline - time.monotonic())) as response:
            attachments = json.load(response)
        url = next(
            (a.get("browser_download_url", "") for a in attachments if a.get("name") == latest.filename), ""
        )
        manifest_url = next(
            (
                a.get("browser_download_url", "")
                for a in attachments
                if a.get("name") == latest.filename + ".manifest.json"
            ),
            "",
        )
        releases[0] = Release(
            latest.tag,
            latest.body,
            source,
            (url or manifest_url) if (url or manifest_url).startswith("https://") else "",
            latest.filename,
            split_manifest=not url and bool(manifest_url),
            attachments=tuple((a["name"], a.get("browser_download_url", "")) for a in attachments),
        )
    return releases


def check_releases(timeout: float = CHECK_TIMEOUT) -> list[Release]:
    """Probe both mirrors concurrently; choose the newest, preferring GitHub on ties.

    Daemon network threads cannot delay process exit if an OS DNS call stalls.
    The coordinator never waits for them beyond the shared deadline.
    """
    deadline = time.monotonic() + timeout
    results: Queue = Queue()

    def probe(source: str) -> None:
        try:
            releases = fetch_releases(source, deadline)
            if releases:
                log.info(
                    "%s latest release: %s", "GitHub" if source == "github" else "Gitee", releases[0].tag
                )
            results.put((source, releases, "No stable releases since v1.0.1" if not releases else ""))
        except Exception as error:
            log.warning("%s release check failed: %s", source.title(), error)
            results.put((source, None, str(error)))

    for source in REPOSITORIES:
        threading.Thread(target=probe, args=(source,), daemon=True).start()
    received = {}
    errors = dict.fromkeys(REPOSITORIES, "Timed out")
    while len(received) < 2:
        try:
            source, releases, error = results.get(timeout=max(0, deadline - time.monotonic()))
        except Empty:
            break
        received[source] = releases
        errors[source] = error
    available = [received[source] for source in REPOSITORIES if received.get(source)]
    if available:
        return max(
            available, key=lambda releases: (stable_version(releases[0].tag), releases[0].source == "github")
        )
    raise ConnectionError("; ".join(f"{source.title()}: {error}" for source, error in errors.items()))


class DownloadCancelledError(Exception):
    """The user closed the download dialog."""


class DownloadCancellation:
    """Cooperative cancellation with socket shutdown to interrupt a blocked read."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._response = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            # Closing a buffered response can block behind read(); shutdown wakes
            # the reader instead, and the worker owns closing the response.
            connection = getattr(getattr(getattr(self._response, "fp", None), "raw", None), "_sock", None)
            if connection is not None:
                with suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)

    def check(self) -> None:
        if self._cancelled.is_set():
            raise DownloadCancelledError()

    @contextmanager
    def open(self, request: Request):
        self.check()
        with urlopen(request, timeout=10) as response:
            with self._lock:
                self._response = response
            try:
                self.check()
                yield response
            finally:
                with self._lock:
                    self._response = None


def download_release(
    release: Release,
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
    cancellation: DownloadCancellation | None = None,
) -> Path:
    """Stream to a temporary file, preserving an existing destination on failure."""
    if not release.download_url:
        raise ValueError("No Windows ZIP attached to this release")
    temporary = destination.with_name(destination.name + ".part")
    cancellation = cancellation or DownloadCancellation()
    try:
        cancellation.check()
        if release.split_manifest:
            _download_parts(release, temporary, progress, cancellation)
            if not zipfile.is_zipfile(temporary):
                raise OSError("The download is not a ZIP archive")
            cancellation.check()
            temporary.replace(destination)
            return destination
        request = Request(release.download_url, headers={"User-Agent": "NightreignOverlayHelper"})
        with cancellation.open(request) as response, temporary.open("wb") as output:
            expected = response.headers.get("Content-Length")
            expected_size = int(expected) if expected else 0
            total = 0
            if progress:
                progress(0, expected_size)
            while chunk := response.read(1024 * 1024):
                cancellation.check()
                output.write(chunk)
                total += len(chunk)
                if progress:
                    progress(total, expected_size)
            cancellation.check()
            if expected and total != int(expected):
                raise OSError("Incomplete download")
        if not zipfile.is_zipfile(temporary):
            raise OSError("The download is not a ZIP archive")
        cancellation.check()
        temporary.replace(destination)
    except Exception:
        cancellation.check()
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _download_parts(
    release: Release,
    temporary: Path,
    progress: Callable[[int, int], None] | None,
    cancellation: DownloadCancellation,
) -> None:
    with cancellation.open(Request(release.download_url)) as response:
        payload = response.read(1024 * 1024 + 1)
    cancellation.check()
    if len(payload) > 1024 * 1024:
        raise ValueError("Split manifest too large")
    manifest = json.loads(payload)
    parts = manifest.get("parts", [])
    if (
        manifest.get("format") != 1
        or manifest.get("filename") != release.filename
        or not isinstance(parts, list)
        or not 1 <= len(parts) <= 100
    ):
        raise ValueError("Invalid split manifest")
    urls = dict(release.attachments)
    digest = hashlib.sha256()
    total = 0
    if progress:
        progress(0, manifest["size"])
    with temporary.open("wb") as output:
        for index, part in enumerate(parts, 1):
            cancellation.check()
            name = f"{release.filename}.{index:03d}"
            url = urls.get(name, "")
            if part.get("name") != name or not url.startswith("https://"):
                raise ValueError("Missing or invalid split attachment")
            part_hash = hashlib.sha256()
            size = 0
            with cancellation.open(Request(url)) as response:
                while chunk := response.read(1024 * 1024):
                    cancellation.check()
                    size += len(chunk)
                    if size > part["size"]:
                        raise ValueError("Split attachment exceeds expected size")
                    output.write(chunk)
                    part_hash.update(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(total + size, manifest["size"])
            cancellation.check()
            if size != part["size"] or part_hash.hexdigest() != part["sha256"]:
                raise ValueError("Split attachment verification failed")
            total += size
    if total != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
        raise ValueError("Merged ZIP verification failed")
