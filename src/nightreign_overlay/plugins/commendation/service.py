"""User-clicked comments in an owned, short-lived Steam HTML helper process."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from nightreign_overlay.core.steam import current_steam_account, valid_steam_id
from nightreign_overlay.plugins.p2p_latency.api import P2PStateChanged, PeerSnapshot, helper_path

from .config import CommendationConfig
from .history import cooldown_state, history_directory
from .session import ExpeditionRoster, Player


class CommendationService(QObject):
    rowsChanged = pyqtSignal(object)
    statusChanged = pyqtSignal(str)

    def __init__(
        self,
        config: CommendationConfig,
        parent=None,
        *,
        clock=time.monotonic,
        account_reader: Callable[[], str] = current_steam_account,
        history: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.clock = clock
        self.account_reader = account_reader
        self.history = history or history_directory()
        self.roster = ExpeditionRoster()
        self.recent: list[Player] = []
        self.reviews: dict[str, tuple[Player, float]] = {}
        self.feedback: dict[str, str] = {}
        self.busy = ""
        self._busy_account = ""
        self._request: dict = {}
        self._response = bytearray()
        self._stopped = False
        self._last_rows: list = []
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.started.connect(self._write_request)
        self.process.readyReadStandardOutput.connect(self._read_response)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.process.kill)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        config.close_seconds.valueChanged.connect(self.tick)

    def on_day_started(self, event) -> None:
        if event.day == 1 and self.roster.start(self.clock()):
            self.reviews.clear()
            self.feedback.clear()
            self.tick()

    def on_snapshot(self, event: PeerSnapshot) -> None:
        if self.roster.account and self.roster.account != event.account:
            self.reviews.clear()
            self.recent.clear()
            self.feedback.clear()
        departed = self.roster.snapshot(event.peers, event.account, self.clock())
        self._show(departed)

    def on_status(self, event: P2PStateChanged) -> None:
        if event.status.state == "game_exited":
            self._show(self.roster.finish())
        elif event.status.state != "steam_ready":
            self.roster.pause()

    def _show(self, players: list[Player]) -> None:
        if players:
            self.recent = list(self.roster.roster.values())[:2] or list(players)[:2]
        for player in players:
            self.reviews[player.steam_id] = (player, self.clock())
        self.tick()

    def show_recent(self) -> None:
        self._show(self.recent or list(self.roster.roster.values()) or list(self.roster.peers.values()))

    def dismiss(self) -> None:
        self.reviews.clear()
        self.tick()

    def tick(self, _value=None) -> None:
        if self._stopped:
            return
        now, account = self.clock(), self.account_reader()
        rows = []
        for target, (player, shown) in list(self.reviews.items()):
            if now - shown >= self.config.close_seconds.value:
                del self.reviews[target]
                continue
            state = cooldown_state(self.history, account, target)
            if player.account != account or not valid_steam_id(player.account):
                state = "account_changed"
            elif self.busy == target:
                state = "sending"
            elif state == "ready":
                state = self.feedback.get(target, "ready")
            rows.append(
                {
                    "steam_id": target,
                    "name": player.name,
                    "state": state,
                    "enabled": not self.busy and state in {"ready", "error", "precondition", "rejected"},
                }
            )
        if rows != self._last_rows:
            self._last_rows = rows
            self.rowsChanged.emit(rows)

    def send(self, target: str) -> None:
        self.tick()
        if (
            self._stopped
            or self.busy
            or not any(row["steam_id"] == target and row["enabled"] for row in self._last_rows)
        ):
            return
        player, _ = self.reviews[target]
        comment = self.config.comment.value.strip()
        if not comment or len(comment) > 500 or "\0" in comment:
            self.statusChanged.emit("invalid_comment")
            return
        helper = helper_path()
        if not helper.is_file():
            self.statusChanged.emit("helper_missing")
            return
        self.busy, self._busy_account = target, player.account
        self._request = {"target": target, "comment": comment, "expected_account": player.account}
        self._response.clear()
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("NROH_COMMENDATION_DIR", str(self.history.resolve()))
        self.process.setProcessEnvironment(environment)
        self.process.setProgram(str(helper))
        self.process.setArguments(["--commend"])
        self.process.setWorkingDirectory(str(helper.parent))
        self.process.start()
        self.timeout.start(110_000)
        self.tick()

    def _write_request(self) -> None:
        self.process.write((json.dumps(self._request, ensure_ascii=False) + "\n").encode("utf-8"))
        self.process.closeWriteChannel()

    def _read_response(self) -> None:
        self._response.extend(bytes(self.process.readAllStandardOutput()))
        if len(self._response) > 16_384:
            self.process.kill()
            del self._response[16_384:]

    def _finished(self, *_args) -> None:
        self.timeout.stop()
        self._read_response()
        state = "unknown"
        try:
            response = json.loads(self._response.decode("utf-8-sig"))
            candidate = response["state"]
            if candidate in {"sent", "rejected", "precondition", "unknown", "cooldown", "error"}:
                state = candidate
        except (ValueError, KeyError, TypeError):
            pass
        if self.busy:
            self.feedback[self.busy] = state
        self.busy = ""
        self.statusChanged.emit(state)
        self.tick()

    def _error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.timeout.stop()
            self.feedback[self.busy] = "error"
            self.busy = ""
            self.statusChanged.emit("helper_missing")
            self.tick()

    def stop(self) -> None:
        self._stopped = True
        self.timer.stop()
        self.timeout.stop()
        self.reviews.clear()
        # An uncertain POST is never replayed; the native reservation survives a kill.
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        self.rowsChanged.emit([])
