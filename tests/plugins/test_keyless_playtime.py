from __future__ import annotations

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QNetworkReply, QNetworkRequest

from nightreign_overlay.plugins.p2p_latency.models import P2PPeer
from nightreign_overlay.plugins.p2p_latency.playtime import MAX_PAGE_BYTES, PlaytimeService
from nightreign_overlay.plugins.p2p_latency.public_playtime import parse_public_playtime

TARGET = "76561198000000002"


def profile(hours="12.5", app="2622380") -> bytes:
    return (
        f'<div class="recent_game"><div class="game_info"><a href="https://steamcommunity.com/app/{app}/">Game</a>'
        f'<div class="game_info_details">{hours} hrs on record</div></div></div>'
    ).encode()


@pytest.mark.parametrize(("hours", "minutes"), [("12.5", 750), ("1,234.5", 74070), ("0", 0), ("0.1", 6)])
def test_public_profile_total_playtime(hours, minutes):
    assert parse_public_playtime(profile(hours)) == minutes


@pytest.mark.parametrize(
    "page", [b"Private profile", b"Please log in", b"Rate limited", profile(app="1245620"), profile() * 2]
)
def test_unavailable_or_ambiguous_never_means_zero(page):
    assert parse_public_playtime(page) is None


def test_other_games_cannot_supply_nightreign_hours():
    assert parse_public_playtime(profile("400", "1245620") + profile("12.5")) == 750


class Reply(QObject):
    readyRead = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, request, parent):
        super().__init__(parent)
        self.request = request
        self.data = b""
        self.aborted = False
        self.failed = False

    def read(self, size):
        if not self.data:
            return None  # Real PyQt QNetworkReply returns None for some EOF reads.
        result, self.data = self.data[:size], self.data[size:]
        return result

    def error(self):
        return (
            QNetworkReply.NetworkError.OperationCanceledError
            if self.aborted or self.failed
            else QNetworkReply.NetworkError.NoError
        )

    def abort(self):
        if not self.aborted:
            self.aborted = True
            self.finished.emit()

    def complete(self, data, *, failed=False):
        self.data, self.failed = data, failed
        self.readyRead.emit()
        if not self.aborted:
            self.finished.emit()


class Network(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.replies = []

    def get(self, request):
        reply = Reply(request, self)
        self.replies.append(reply)
        return reply


@pytest.fixture
def service(qapp, monkeypatch):
    monkeypatch.setattr("nightreign_overlay.plugins.p2p_latency.playtime.QNetworkAccessManager", Network)
    now = [0.0]
    instance = PlaytimeService(clock=lambda: now[0])
    instance.now = now
    yield instance
    instance.stop()
    instance.deleteLater()


def peer(target=TARGET):
    return P2PPeer(target, "Someone", 30, 0.99, "messages", "connected")


def test_disabled_sends_nothing_and_request_is_anonymous(service):
    service.set_peers([peer()])
    assert not service._network.replies
    service.set_enabled(True)
    request = service._network.replies[0].request
    assert request.url().toString() == f"https://steamcommunity.com/profiles/{TARGET}/?l=english"
    assert (
        request.attribute(QNetworkRequest.Attribute.CookieLoadControlAttribute)
        == QNetworkRequest.LoadControl.Manual
    )
    assert (
        request.attribute(QNetworkRequest.Attribute.CookieSaveControlAttribute)
        == QNetworkRequest.LoadControl.Manual
    )
    service._network.replies[0].complete(profile())
    assert service.results[TARGET].minutes == 750
    service.set_enabled(False)
    assert service.results == {} and not service.timer.isActive()


def test_concurrency_cache_and_missing_data_retry(service):
    service.set_peers([peer(str(int(TARGET) + n)) for n in range(3)])
    service.set_enabled(True)
    assert len(service._network.replies) == 2
    service._network.replies[0].complete(b"private")
    assert service.results[TARGET].state == "unavailable"
    assert len(service._network.replies) == 3
    service._query()
    assert len(service._network.replies) == 3
    for reply in service._network.replies[1:]:
        reply.complete(profile())
    service.now[0] = 301
    service._query()
    assert len(service._network.replies) == 4


@pytest.mark.parametrize("action", ["disable", "leave"])
def test_cancel_and_late_completion_do_not_resurrect_results(service, action):
    service.set_peers([peer()])
    service.set_enabled(True)
    reply = service._network.replies[0]
    if action == "disable":
        service.set_enabled(False)
    else:
        service.set_peers([])
    assert reply.aborted
    reply.complete(profile())
    assert service.results == {}


def test_http_failure_and_response_limit_stay_unavailable(service):
    service.set_peers([peer()])
    service.set_enabled(True)
    service._network.replies[-1].complete(profile(), failed=True)
    assert service.results[TARGET].state == "unavailable"
    service.now[0] = 301
    service._query()
    reply = service._network.replies[-1]
    reply.complete(b"x" * (MAX_PAGE_BYTES + 100))
    assert reply.aborted and service.results[TARGET].minutes is None


def test_invalid_steam_ids_never_become_urls(service):
    service.set_peers([peer("123"), peer("../../profiles/123")])
    service.set_enabled(True)
    assert not service._network.replies


@pytest.mark.parametrize("body", [profile(), b""])
def test_real_qt_network_completion_after_ready_read(qapp, monkeypatch, body):
    """Exercise Qt's real response/EOF behavior without contacting Steam."""
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from PyQt6.QtCore import QUrl
    from PyQt6.QtNetwork import QNetworkAccessManager

    from tests.support.qt import process_events

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class LocalNetwork(QNetworkAccessManager):
        def get(self, request):
            local = QNetworkRequest(request)
            local.setUrl(QUrl(f"http://127.0.0.1:{server.server_port}/"))
            return super().get(local)

    monkeypatch.setattr("nightreign_overlay.plugins.p2p_latency.playtime.QNetworkAccessManager", LocalNetwork)
    instance = PlaytimeService()
    try:
        instance.set_peers([peer()])
        instance.set_enabled(True)
        until = time.monotonic() + 4
        while instance.results[TARGET].state == "loading" and time.monotonic() < until:
            process_events(20)
        assert instance.results[TARGET].state == ("available" if body else "unavailable")
        assert instance.results[TARGET].minutes == (750 if body else None)
        assert not instance._pending
    finally:
        instance.stop()
        instance.deleteLater()
        server.shutdown()
        server.server_close()
        thread.join(2)
