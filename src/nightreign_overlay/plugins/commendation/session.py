"""Pure expedition/departure tracking. Only fresh, successful snapshots count."""

from __future__ import annotations

from dataclasses import dataclass

from nightreign_overlay.core.steam import valid_steam_id
from nightreign_overlay.plugins.p2p_latency.api import P2PPeer

_DAY_ONE_BANNER_GAP = 10


@dataclass(frozen=True)
class Player:
    steam_id: str
    name: str
    account: str


class ExpeditionRoster:
    def __init__(self) -> None:
        self.account = ""
        self.peers: dict[str, Player] = {}
        self.roster: dict[str, Player] = {}
        self.departures: dict[str, float] = {}
        self.reported: set[str] = set()
        self.last_snapshot = float("-inf")
        self.last_day_one = float("-inf")
        self.tracking = False

    def reset(self) -> None:
        self.__init__()

    def start(self, now: float) -> bool:
        # DAY I is published on every banner hit. Debounce the continuous burst,
        # not the expedition's first two minutes: a quick next game is legitimate.
        same_banner = self.tracking and now - self.last_day_one < _DAY_ONE_BANNER_GAP
        self.last_day_one = now
        if same_banner:
            return False
        self.roster = dict(self.peers) if now - self.last_snapshot <= 5 else {}
        self.tracking = True
        self.departures.clear()
        self.reported.clear()
        return True

    def snapshot(self, peers: tuple[P2PPeer, ...], account: str, now: float) -> list[Player]:
        if self.account and account != self.account:
            self.reset()
        self.account = account
        if now - self.last_snapshot > 5:
            self.departures.clear()
        self.last_snapshot = now
        self.peers = {
            p.steam_id: Player(p.steam_id, p.name[:128], account)
            for p in peers
            if valid_steam_id(p.steam_id) and p.state in {"connected", "connecting"}
        }
        if not self.tracking:
            return []
        for target, player in self.peers.items():
            if target in self.roster or len(self.roster) < 2:
                self.roster[target] = player
            self.departures.pop(target, None)
        for target in self.roster.keys() - self.peers.keys() - self.reported:
            self.departures.setdefault(target, now)
        # Confirmation happens on another real snapshot, never merely on a timer.
        left = [target for target, since in self.departures.items() if now - since >= 3]
        result = [self.roster[target] for target in left]
        self.reported.update(left)
        for target in left:
            del self.departures[target]
        return result

    def pause(self) -> None:
        self.last_snapshot = float("-inf")
        self.departures.clear()

    def finish(self) -> list[Player]:
        players = [p for key, p in self.roster.items() if key not in self.reported]
        self.roster.clear()
        self.departures.clear()
        self.reported.clear()
        self.tracking = False
        self.pause()
        return players
