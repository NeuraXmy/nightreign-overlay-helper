from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class P2PPeer:
    steam_id: str
    name: str
    ping_ms: int | None
    quality: float | None
    api: str
    state: str


@dataclass(frozen=True)
class P2PStatus:
    state: str
    message: str
    peer_count: int = 0
    etw_state: str = "disabled"

    @property
    def game_running(self) -> bool:
        return self.state not in {
            "disabled",
            "helper_missing",
            "helper_error",
            "helper_started",
            "helper_restarting",
            "waiting_for_game",
        }


class JsonLineBuffer:
    def __init__(self):
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        lines: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line := line.strip():
                lines.append(line)
        return lines


def parse_helper_message(line: str) -> tuple[str, Any]:
    """Parse and validate one JSONL message emitted by the native helper."""
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ValueError("helper message must be a JSON object")

    message_type = payload.get("type")
    if message_type == "status":
        state = payload.get("state")
        message = payload.get("message")
        etw_state = payload.get("etw_state", "disabled")
        if not isinstance(state, str) or not isinstance(message, str) or not isinstance(etw_state, str):
            raise ValueError("invalid status message")
        return "status", P2PStatus(state=state, message=message, etw_state=etw_state)

    if message_type == "snapshot":
        raw_peers = payload.get("peers")
        if not isinstance(raw_peers, list):
            raise ValueError("invalid snapshot message")

        peers: list[P2PPeer] = []
        for raw_peer in raw_peers:
            if not isinstance(raw_peer, dict):
                raise ValueError("invalid peer entry")
            steam_id = raw_peer.get("steam_id")
            name = raw_peer.get("name")
            api = raw_peer.get("api")
            state = raw_peer.get("state")
            if not all(isinstance(value, str) for value in (steam_id, name, api, state)):
                raise ValueError("invalid peer identity")

            ping = raw_peer.get("ping_ms")
            quality = raw_peer.get("quality")
            if ping is not None and not isinstance(ping, int):
                raise ValueError("invalid peer ping")
            if quality is not None and not isinstance(quality, (int, float)):
                raise ValueError("invalid peer quality")

            peers.append(P2PPeer(
                steam_id=steam_id,
                name=name,
                ping_ms=ping,
                quality=float(quality) if quality is not None else None,
                api=api,
                state=state,
            ))
        return "snapshot", peers

    raise ValueError(f"unknown helper message type: {message_type!r}")
