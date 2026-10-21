"""Mirror GitHub release metadata and runtime ZIPs to a release-only Gitee repo."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def api(method: str, url: str, data: dict | None = None, token: str = ""):
    headers = {"User-Agent": "NightreignOverlayHelper-ReleaseSync", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(data).encode() if data is not None else None
    if payload is not None:
        headers["Content-Type"] = "application/json"
    with urlopen(Request(url, data=payload, headers=headers, method=method), timeout=60) as response:
        payload = response.read()
        return json.loads(payload) if payload else None


PART_SIZE = 50 * 1024 * 1024


def prepare_runtime(path: Path, part_size: int = PART_SIZE) -> list[Path]:
    """Split raw ZIP bytes; the manifest lets clients restore the exact upstream ZIP."""
    if path.stat().st_size <= part_size:
        return [path]
    parts = []
    total_hash = hashlib.sha256()
    with path.open("rb") as source:
        index = 1
        while chunk := source.read(part_size):
            part = path.with_name(f"{path.name}.{index:03d}")
            part.write_bytes(chunk)
            parts.append({"name": part.name, "size": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
            total_hash.update(chunk)
            index += 1
    manifest = path.with_name(path.name + ".manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "format": 1,
                "filename": path.name,
                "size": path.stat().st_size,
                "sha256": total_hash.hexdigest(),
                "parts": parts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return [*(path.with_name(part["name"]) for part in parts), manifest]


def mirror_notes(github: dict, github_repo: str, tag: str, split: bool) -> str:
    body = github["body"] or tag
    body += "\n\n---\n\n## 国内下载 / Mirror download\n\n"
    if split:
        filename = f"nightreign-overlay-helper-{tag}-windows-x64.zip"
        body += (
            "程序 ZIP 以低于 100 MB 的分卷发布。应用内更新会自动下载并合并。手动下载时，"
            "请下载全部 `.001`、`.002` 等分卷至同一目录，按编号顺序合并为 ZIP 后完整解压。\n\n"
            "Windows 命令提示符（cmd）合并示例：\n\n```bat\n"
            f'copy /b "{filename}.???" "{filename}"\n```\n\n'
            "`.manifest.json` 包含各分卷及完整 ZIP 的 SHA-256 校验值。\n\n"
        )
    body += (
        "本镜像仅上传程序；对应源码请从上游同版本 Release 的源码附件获取：\n\n"
        f"[{tag}-sources.zip](https://github.com/{github_repo}/releases/download/{tag}/{tag}-sources.zip)\n"
    )
    return body


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC {message}", flush=True)


def upload_attachment(endpoint: str, path: Path, token: str, timeout: int = 1800) -> None:
    """Stream curl's numeric progress only; never print credentials or server bodies."""
    log(f"Upload start: {path.name}, {path.stat().st_size} bytes, timeout={timeout}s")
    started = time.monotonic()
    last_progress = -float("inf")
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as metrics:
        with subprocess.Popen(
            [
                "curl",
                "--fail",
                "--progress-meter",
                "--show-error",
                "--connect-timeout",
                "30",
                "--max-time",
                str(timeout),
                "--output",
                os.devnull,
                "--write-out",
                "%{json}",
                "--config",
                "-",
                endpoint,
            ],
            stdin=subprocess.PIPE,
            stdout=metrics,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            process.stdin.write(
                f"form = {json.dumps('access_token=' + token)}\nform = {json.dumps('file=@' + str(path))}\n"
            )
            process.stdin.close()
            for line in process.stderr:
                # A curl meter row has 12 numeric/unit/time columns. Ignore all
                # arbitrary error text: it can contain request or server data.
                columns = line.split()
                if len(columns) != 12 or not re.fullmatch(r"[0-9kKMGTPE.: %/s-]+", line.strip()):
                    continue
                now = time.monotonic()
                if now - last_progress >= 15:
                    log(
                        f"Upload progress: {path.name}, sent={columns[4]}% ({columns[5]}), "
                        f"average={columns[7]}B/s, current={columns[11]}B/s, elapsed={now - started:.1f}s"
                    )
                    last_progress = now
            code = process.wait()
        metrics.seek(0)
        try:
            result = json.load(metrics)
        except ValueError:
            result = {}
    fields = (
        "http_code",
        "remote_ip",
        "http_version",
        "time_namelookup",
        "time_connect",
        "time_appconnect",
        "time_pretransfer",
        "time_starttransfer",
        "time_posttransfer",
        "time_total",
        "size_upload",
        "speed_upload",
    )
    # Only explicitly selected scalar metrics are logged. curl's full JSON
    # includes the request URL and must never be dumped wholesale.
    summary = {key: result[key] for key in fields if key in result}
    log(
        f"Upload end: {path.name}, curl={code}, elapsed={time.monotonic() - started:.1f}s, "
        f"{json.dumps(summary)}"
    )
    if code:
        raise RuntimeError(f"Gitee upload failed for {path.name} (curl {code})")


def diagnostic_tag() -> str:
    return f"{os.environ['RELEASE_TAG']}-uploadcheck-{os.environ['GITHUB_RUN_ID']}"


def cleanup_diagnostic() -> None:
    target_tag = diagnostic_tag()
    base = f"https://gitee.com/api/v5/repos/{os.environ['GITEE_REPO']}"
    token = os.environ["GITEE_TOKEN"]
    try:
        release = api("GET", f"{base}/releases/tags/{quote(target_tag, safe='')}", token=token)
    except HTTPError as error:
        if error.code != 404:
            raise
        release = None
    if release:
        api("DELETE", f"{base}/releases/{release['id']}", {"access_token": token})
        log(f"Removed diagnostic release: {target_tag}")


def sync() -> None:
    token = os.environ["GITEE_TOKEN"]
    repo = os.environ["GITEE_REPO"]
    tag = os.environ["RELEASE_TAG"]
    github_repo = os.environ["GITHUB_REPOSITORY"]
    diagnostic = os.environ.get("DIAGNOSTIC_UPLOAD") == "true"
    target_tag = diagnostic_tag() if diagnostic else tag
    log(f"Mirror start: GitHub {tag} -> Gitee {target_tag}; diagnostic={diagnostic}")
    github = api(
        "GET",
        f"https://api.github.com/repos/{github_repo}/releases/tags/{quote(tag, safe='')}",
        token=os.environ["GH_TOKEN"],
    )
    if github.get("draft"):
        raise ValueError("Draft releases cannot be mirrored")
    names = [f"nightreign-overlay-helper-{tag}-windows-x64.zip"]
    files = [Path("release") / name for name in names]
    assets = {a["name"]: a for a in github["assets"]}
    for path in files:
        if not path.is_file() or path.stat().st_size != assets[path.name]["size"]:
            raise ValueError(f"Missing or mismatched GitHub attachment: {path.name}")
    files = prepare_runtime(files[0])
    base = f"https://gitee.com/api/v5/repos/{repo}"
    metadata = {
        "access_token": token,
        "tag_name": target_tag,
        "name": github["name"] or tag,
        "body": mirror_notes(github, github_repo, tag, len(files) > 1),
        "prerelease": True if diagnostic else github["prerelease"],
    }
    try:
        release = api("GET", f"{base}/releases/tags/{quote(target_tag, safe='')}", token=token)
    except HTTPError as error:
        if error.code != 404:
            raise
        release = None
    # Gitee also returns HTTP 200 with a null body for a missing release.
    if release is None:
        repository = api("GET", base, token=token)
        # Gitee requires a commit for tags: use the mirror's own initial README commit.
        metadata["target_commitish"] = repository["default_branch"]
        release = api("POST", f"{base}/releases", metadata)
    else:
        release = api("PATCH", f"{base}/releases/{release['id']}", metadata)
    endpoint = f"{base}/releases/{release['id']}/attach_files"
    attached = {a["name"]: a for a in api("GET", endpoint + "?per_page=100", token=token)}
    for path in files:
        previous = attached.get(path.name)
        if previous and previous["size"] == path.stat().st_size:
            log(f"Attachment already present: {path.name} ({previous['size']} bytes), skipped")
            continue
        if previous:
            api("DELETE", f"{endpoint}/{previous['id']}", {"access_token": token})
        upload_attachment(endpoint, path, token, timeout=300 if diagnostic else 1800)
    final = {a["name"]: a for a in api("GET", endpoint + "?per_page=100", token=token)}
    if any(final.get(path.name, {}).get("size") != path.stat().st_size for path in files):
        raise RuntimeError("Gitee release attachment verification failed")
    log(f"Mirror complete: {target_tag}, {len(files)} attachments verified")


if __name__ == "__main__":
    if "--cleanup-diagnostic" in sys.argv:
        cleanup_diagnostic()
    else:
        sync()
