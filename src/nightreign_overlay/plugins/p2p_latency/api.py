"""Fresh Steam roster events for optional teammate features."""

from dataclasses import dataclass
from pathlib import Path

from .models import P2PPeer, P2PStatus


@dataclass(frozen=True)
class PeerSnapshot:
    peers: tuple[P2PPeer, ...]
    account: str


@dataclass(frozen=True)
class P2PStateChanged:
    status: P2PStatus


def helper_path() -> Path:
    from .service import resolve_helper_path

    return resolve_helper_path()
