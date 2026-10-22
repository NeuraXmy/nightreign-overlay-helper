"""Run inside CNB: download and verify the upstream ZIP, then publish it locally."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC {message}", flush=True)


def api(method: str, url: str, token: str = "", data: dict | None = None):
    accept = (
        "application/vnd.github+json"
        if url.startswith("https://api.github.com/")
        else "application/vnd.cnb.api+json"
    )
    headers = {"Accept": accept, "User-Agent": "NightreignOverlayHelper-Sync"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = None if data is None else json.dumps(data).encode()
    if payload is not None:
        headers["Content-Type"] = "application/json"
    with urlopen(Request(url, data=payload, headers=headers, method=method), timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else None


def transfer(url: str, path: Path, *, upload: bool = False) -> None:
    """Keep signed URLs out of argv and logs, emit only transfer metrics."""
    started = time.monotonic()
    operation = "Upload" if upload else "Download"
    log(f"{operation} start: {path.name}")
    args = [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--connect-timeout",
        "30",
        "--max-time",
        "900",
        "--config",
        "-",
        "--write-out",
        "%{http_code} %{size_download} %{size_upload} %{speed_download} %{speed_upload} %{time_total}",
    ]
    if upload:
        args += ["--upload-file", str(path), "--output", os.devnull]
    else:
        args += ["--output", str(path)]
    result = subprocess.run(
        args, input="url = " + json.dumps(url) + "\n", text=True, capture_output=True, check=False
    )
    metrics = result.stdout.strip()
    if not re.fullmatch(r"[\d. ]+", metrics):
        metrics = "unavailable"
    log(
        f"{operation} end: curl={result.returncode}, elapsed={time.monotonic() - started:.1f}s, "
        f"HTTP/received/sent/download_Bps/upload_Bps/seconds={metrics}"
    )
    if result.returncode:
        raise RuntimeError(f"{operation} failed (curl {result.returncode})")


def sync() -> None:
    tag = os.environ["RELEASE_TAG"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Expected a stable version tag")
    repo = os.environ.get("CNB_REPO", "NeuraXmy/nightreign-overlay-helper")
    upstream = os.environ.get("GITHUB_REPOSITORY", "NeuraXmy/nightreign-overlay-helper")
    token = os.environ["CNB_TOKEN"]
    # A trigger may pass authenticated GitHub metadata to avoid anonymous API limits.
    if os.environ.get("UPSTREAM_RELEASE_JSON"):
        github = json.loads(os.environ["UPSTREAM_RELEASE_JSON"])
    else:
        github = api("GET", f"https://api.github.com/repos/{upstream}/releases/tags/{tag}")
    if github["tag_name"] != tag or github.get("draft") or github.get("prerelease"):
        raise ValueError("Expected the matching public stable GitHub release")
    filename = f"nightreign-overlay-helper-{tag}-windows-x64.zip"
    asset = next(a for a in github["assets"] if a["name"] == filename)
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("GitHub SHA-256 digest is required")
    url = asset["browser_download_url"]
    if url != f"https://github.com/{upstream}/releases/download/{tag}/{filename}":
        raise ValueError("Unexpected upstream download URL")
    path = Path(filename)
    transfer(url, path)
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if path.stat().st_size != asset["size"] or "sha256:" + actual != digest:
        raise ValueError("Upstream runtime size or SHA-256 mismatch")
    log(f"Verified upstream runtime: size={path.stat().st_size}, SHA-256={actual}")
    base = f"https://api.cnb.cool/{repo}/-/releases"
    try:
        release = api("GET", f"{base}/tags/{tag}", token)
    except HTTPError as error:
        if error.code != 404:
            raise
        release = None
    metadata = {
        "tag_name": tag,
        "target_commitish": "main",
        "name": github.get("name") or tag,
        "body": github.get("body") or tag,
        "draft": False,
        "prerelease": False,
        "make_latest": "legacy",
    }
    if release is None:
        release = api("POST", base, token, metadata)
    else:
        api("PATCH", f"{base}/{release['id']}", token, metadata)
    existing = next((a for a in (release.get("assets") or []) if a["name"] == filename), None)
    if existing and existing.get("size") == path.stat().st_size and existing.get("hash_value") == actual:
        log("Matching runtime already published; skipped")
        return
    upload = api(
        "POST",
        f"{base}/{release['id']}/asset-upload-url",
        token,
        {"asset_name": filename, "size": path.stat().st_size, "overwrite": True},
    )
    transfer(upload["upload_url"], path, upload=True)
    verify = upload["verify_url"]
    if verify.startswith("/"):
        verify = "https://api.cnb.cool" + verify
    if not verify.startswith(f"{base}/{release['id']}/asset-upload-confirmation/"):
        raise ValueError("Unexpected upload confirmation URL")
    api("POST", verify, token)
    final = api("GET", f"{base}/tags/{quote(tag, safe='')}", token)
    attached = next(a for a in final["assets"] if a["name"] == filename)
    if attached["size"] != path.stat().st_size or attached.get("hash_value") != actual:
        raise ValueError("CNB published attachment verification failed")
    log(f"CNB release verified: {tag}, {filename}")


if __name__ == "__main__":
    sync()
