"""Exercise the published Windows helper entry points without Steam or game operations.

Each process uses an empty, isolated recovery directory. Supervisors must publish
an idle capability and exit after their client grace period; finite tasks have no
queued request or journal. Run after publishing, for both single-file and onedir.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _environment(root: Path) -> dict[str, str]:
    environment = dict(os.environ, NROH_IDENTITY_DIR=str(root))
    environment.pop("SteamAppId", None)
    environment.pop("SteamGameId", None)
    return environment


def _status(root: Path) -> dict:
    try:
        return json.loads((root / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check(helper: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Published helper startup checks require Windows.")
    helper = helper.resolve(strict=True)
    assembly = helper.with_suffix(".dll")
    data = (assembly if assembly.is_file() else helper).read_bytes()
    # Legacy helpers ignore NROH_IDENTITY_DIR. Never launch those against the
    # user's real recovery directory, even if a caller supplies an old package.
    if "NROH_IDENTITY_DIR".encode("utf-16-le") not in data:
        raise RuntimeError("This helper lacks isolated recovery directories; rebuild the native component.")
    detached = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with tempfile.TemporaryDirectory(prefix="nroh-startup-") as temporary:
        root = Path(temporary)
        supervisors: list[tuple[subprocess.Popen, Path, str]] = []
        try:
            for slot in (None, 0, 1):
                identity = root / ("legacy" if slot is None else f"slot-{slot}")
                status_root = identity if slot is None else identity / f"match-{slot}"
                args = ["--identity-worker"] if slot is None else ["--match-worker", str(slot)]
                process = subprocess.Popen(
                    [str(helper), *args],
                    cwd=helper.parent,
                    env=_environment(identity),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=detached,
                )
                lifecycle = "recovery_only_v3" if slot is None else "match_hold_v5"
                supervisors.append((process, status_root, lifecycle))

            deadline = time.monotonic() + 15
            while True:
                ready = True
                for process, directory, lifecycle in supervisors:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"Detached supervisor crashed before readiness: {process.returncode}"
                        )
                    status = _status(directory)
                    ready &= (
                        status.get("state") == "idle"
                        and status.get("accepts_begin") is True
                        and status.get("steam_connected") is False
                        and status.get("steam_lifecycle") == lifecycle
                    )
                if ready:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Detached supervisors did not publish their idle capability.")
                time.sleep(0.05)
            print("PASS detached supervisors: legacy recovery and both teammate slots", flush=True)

            for slot in (None, 0, 1):
                identity = root / ("task-legacy" if slot is None else f"task-{slot}")
                directory = identity if slot is None else identity / f"match-{slot}"
                args = (
                    ["--identity-task", str(os.getpid())]
                    if slot is None
                    else ["--match-task", str(slot), str(os.getpid())]
                )
                result = subprocess.run(
                    [str(helper), *args],
                    cwd=helper.parent,
                    env=_environment(identity),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=15,
                    check=False,
                )
                status = _status(directory)
                if (
                    result.returncode != 0
                    or status.get("state") != "idle"
                    or status.get("steam_connected") is not False
                    or status.get("task_exiting") is not True
                ):
                    raise RuntimeError(f"Finite recovery task did not exit idle: {result.returncode}")
            print("PASS finite recovery tasks: no console and no Steam session", flush=True)

            result = subprocess.run(
                [str(helper), "--commend"],
                cwd=helper.parent,
                env=_environment(root / "comment"),
                input='{"comment":"启动检查：无效请求"}\n',
                capture_output=True,
                encoding="utf-8-sig",
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
                check=False,
            )
            if result.returncode != 1 or json.loads(result.stdout).get("state") != "error":
                raise RuntimeError("Comment pipe mode did not reject the invalid request.")
            print("PASS UTF-8 comment pipe: invalid request rejected before Steam initialization", flush=True)

            deadline = time.monotonic() + 70
            while any(process.poll() is None for process, _, _ in supervisors):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Idle supervisors did not exit after the client grace period.")
                time.sleep(0.1)
            for process, directory, _ in supervisors:
                status = _status(directory)
                if (
                    process.returncode != 0
                    or status.get("worker_exiting") is not True
                    or status.get("steam_connected") is not False
                ):
                    raise RuntimeError("An idle supervisor failed to exit without a Steam session.")
            if list(root.rglob("journal-*.json")):
                raise RuntimeError("An idle startup unexpectedly created a recovery transaction.")
            print("PASS idle supervisors exit normally; no communication transactions created", flush=True)
        finally:
            # These are only this check's empty, isolated supervisors. Never stop
            # a production recovery owner or touch the user's recovery files.
            for process, _, _ in supervisors:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("helper", type=Path)
    check(parser.parse_args().helper)


if __name__ == "__main__":
    main()
