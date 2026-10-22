"""Trigger and await CNB-native release synchronization from GitHub Actions."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from scripts.sync_cnb_release import api, log


def trigger() -> None:
    tag = os.environ["RELEASE_TAG"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("CNB mirror currently accepts stable release tags only")
    repo = os.environ.get("CNB_REPO", "NeuraXmy/nightreign-overlay-helper")
    upstream = os.environ["GITHUB_REPOSITORY"]
    github = api(
        "GET", f"https://api.github.com/repos/{upstream}/releases/tags/{tag}", os.environ["GH_TOKEN"]
    )
    if github.get("draft") or github.get("prerelease"):
        raise ValueError("CNB mirror currently accepts public stable releases only")
    script = Path(__file__).with_name("sync_cnb_release.py").read_text(encoding="utf-8")
    # Pass the checked-out synchronization code as build configuration so the
    # mirror does not need a second, manually maintained copy of this script.
    config = {
        "main": {
            "api_trigger": [
                {
                    "name": "sync-github-release",
                    "docker": {"image": "python:3.13"},
                    "stages": [
                        {
                            "name": "Download, verify and publish upstream runtime",
                            "script": "python - <<'CNB_SYNC_PY'\n" + script + "\nCNB_SYNC_PY",
                        }
                    ],
                }
            ]
        }
    }
    metadata = {key: github.get(key) for key in ("tag_name", "name", "body", "draft", "prerelease", "assets")}
    token = os.environ["CNB_TOKEN"]
    base = f"https://api.cnb.cool/{repo}/-/build"
    result = api(
        "POST",
        base + "/start",
        token,
        {
            "branch": "main",
            "event": "api_trigger",
            "title": f"Mirror GitHub {tag}",
            "config": json.dumps(config),
            "env": {
                "RELEASE_TAG": tag,
                "CNB_REPO": repo,
                "GITHUB_REPOSITORY": upstream,
                "UPSTREAM_RELEASE_JSON": json.dumps(metadata),
            },
        },
    )
    if not result.get("success") or not result.get("sn"):
        raise RuntimeError("CNB rejected the build trigger")
    log(f"CNB synchronization triggered: {result['sn']}")
    log(f"CNB build: https://cnb.cool/{repo}/-/build/logs/{result['sn']}")
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        state = api("GET", base + f"/status/{result['sn']}", token)
        status = state.get("status")
        if status == "success":
            log(f"CNB synchronization completed: {tag}")
            return
        if status in ("error", "failed", "cancelled", "canceled", "timeout"):
            raise RuntimeError(f"CNB synchronization failed: {status}; see CNB build logs")
        time.sleep(10)
    raise TimeoutError("CNB build did not finish within 20 minutes; inspect it before retrying")


if __name__ == "__main__":
    trigger()
