"""Bounded anonymous public-profile queries; no API key or Steam login required."""

from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from nightreign_overlay.core.steam import valid_steam_id

from .models import P2PPeer
from .public_playtime import parse_public_playtime

MAX_PAGE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class PlaytimeResult:
    state: str
    minutes: int | None = None


class PlaytimeService(QObject):
    resultsChanged = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None, *, clock=time.monotonic) -> None:
        super().__init__(parent)
        self.clock = clock
        self.enabled = False
        self._peers: set[str] = set()
        self.results: dict[str, PlaytimeResult] = {}
        self._cache: dict[str, tuple[float, PlaytimeResult]] = {}
        self._pending: dict[str, QNetworkReply] = {}
        self._network = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setInterval(30_000)
        self.timer.timeout.connect(self._query)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self.timer.start()
            self._query()
        else:
            self.stop()

    def stop(self) -> None:
        self.enabled = False
        self.timer.stop()
        pending, self._pending = self._pending, {}
        for reply in pending.values():
            reply.abort()
        self.results.clear()
        self.resultsChanged.emit({})

    def set_peers(self, peers: list[P2PPeer]) -> None:
        self._peers = {peer.steam_id for peer in peers if valid_steam_id(peer.steam_id)}
        for target in set(self._pending) - self._peers:
            self._pending.pop(target).abort()
        self.results = {key: value for key, value in self.results.items() if key in self._peers}
        self.resultsChanged.emit(dict(self.results))
        self._query()

    def _query(self) -> None:
        if not self.enabled:
            return
        now = self.clock()
        for target in sorted(self._peers):
            if target in self._pending:
                continue
            cached = self._cache.get(target)
            if cached and now < cached[0]:
                self.results[target] = cached[1]
            elif len(self._pending) < 2:
                self._start(target)
        self.resultsChanged.emit(dict(self.results))

    def _start(self, target: str) -> None:
        request = QNetworkRequest(QUrl(f"https://steamcommunity.com/profiles/{target}/?l=english"))
        request.setTransferTimeout(10_000)
        request.setRawHeader(b"Accept-Language", b"en-US,en;q=0.8")
        request.setRawHeader(b"User-Agent", b"NightreignOverlayHelper/1.0")
        request.setAttribute(
            QNetworkRequest.Attribute.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual
        )
        request.setAttribute(
            QNetworkRequest.Attribute.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual
        )
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy,
        )
        reply = self._network.get(request)
        self._pending[target] = reply
        self.results[target] = PlaytimeResult("loading")
        data = bytearray()
        oversized = False
        deadline = QTimer(reply)
        deadline.setSingleShot(True)
        deadline.timeout.connect(reply.abort)

        def read() -> None:
            nonlocal oversized
            if oversized:
                return
            # PyQt can return None at EOF, including the final finished callback
            # after readyRead already consumed the entire response.
            chunk = reply.read(MAX_PAGE_BYTES + 1 - len(data))
            if chunk:
                data.extend(bytes(chunk))
            if len(data) > MAX_PAGE_BYTES:
                oversized = True
                reply.abort()

        def finish() -> None:
            deadline.stop()
            read()
            active = self._pending.get(target) is reply
            if active:
                del self._pending[target]
                result = PlaytimeResult("unavailable")
                if reply.error() == QNetworkReply.NetworkError.NoError and len(data) <= MAX_PAGE_BYTES:
                    try:
                        minutes = parse_public_playtime(bytes(data))
                        if minutes is not None:
                            result = PlaytimeResult("available", minutes)
                    except (ValueError, UnicodeError):
                        pass
                self._cache[target] = (self.clock() + (600 if result.state == "available" else 300), result)
                while len(self._cache) > 64:
                    del self._cache[next(iter(self._cache))]
                if self.enabled and target in self._peers:
                    self.results[target] = result
                self._query()
            reply.deleteLater()

        reply.readyRead.connect(read)
        reply.finished.connect(finish)
        deadline.start(10_000)
