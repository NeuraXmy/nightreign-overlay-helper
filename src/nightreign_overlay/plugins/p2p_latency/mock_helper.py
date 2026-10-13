"""macOS development helper: JSONL over real process pipes, with no Steam/ETW dependency.

Runs the same one-second polling cadence as the Windows helper. The repeating 32-second
scenario includes empty lists, unavailable metrics, all ping colours and a replacement peer.
"""

from __future__ import annotations

import json
import sys
import threading


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def peer(steam_id: str, name: str, ping: int | None, quality: float | None, api: str) -> dict:
    return {
        "steam_id": steam_id,
        "name": name,
        "ping_ms": ping,
        "quality": quality,
        "api": api,
        "state": "connecting" if ping is None else "connected",
    }


def snapshot(tick: int) -> list[dict]:
    phase = tick % 32
    if phase < 2 or phase >= 28:
        return []
    if phase < 6:
        return [peer("10001", "模拟队友 A", None, None, "legacy")]
    first = peer("10001", "模拟队友 A", (45, 105, 185)[(phase // 4) % 3], 0.93, "legacy")
    if phase < 16:
        return [first, peer("10002", "模拟队友 B", 76, 0.98, "messages")]
    return [peer("10003", "模拟队友 C", 162, 0.64, "legacy"), first]


def main() -> None:
    stopping = threading.Event()

    def read_commands() -> None:
        for line in sys.stdin:
            if line.strip().lower() == "shutdown":
                break
        stopping.set()

    threading.Thread(target=read_commands, daemon=True).start()
    emit(
        {
            "type": "status",
            "state": "waiting_for_game",
            "message": "macOS 模拟：等待游戏",
            "etw_state": "waiting",
        }
    )
    if stopping.wait(1):
        return
    emit(
        {
            "type": "status",
            "state": "steam_ready",
            "message": "macOS 模拟数据（非真实网络测量）",
            "etw_state": "simulated",
        }
    )
    tick = 0
    while not stopping.is_set():
        emit({"type": "snapshot", "peers": snapshot(tick)})
        tick += 1
        stopping.wait(1)


if __name__ == "__main__":
    main()
