"""Read the account-scoped, durable native comment journal (including legacy records)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from nightreign_overlay.core.paths import DATA_DIR_ENV, user_data_dir
from nightreign_overlay.core.steam import valid_steam_id


def history_directory() -> Path:
    if os.getenv(DATA_DIR_ENV) or not os.getenv("LOCALAPPDATA"):
        return user_data_dir() / "commendations"
    # Keep the old per-account reservation, including uncertain/crashed requests.
    return Path(os.environ["LOCALAPPDATA"]) / "NightreignOverlayHelper/identity/commendations"


def cooldown_state(root: Path, account: str, target: str, *, now: datetime | None = None) -> str:
    if not valid_steam_id(account) or not valid_steam_id(target):
        return "account_missing"
    path = root / f"{account}-{target}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["account"] != account or record["target"] != target:
            return "history_error"
        state = record["state"]
        if state not in {"sending", "unknown", "sent", "rejected", "precondition"}:
            return "history_error"
        until = datetime.fromisoformat(record["cooldown_until"])
        if until.tzinfo is None:
            return "history_error"
        if until > (now or datetime.now(UTC)):
            return (
                "unknown"
                if state in {"sending", "unknown"}
                else "cooldown"
                if state == "sent"
                else "retry_later"
            )
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError):
        return "history_error"
    return "ready"
