from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest

from nightreign_overlay.core.steam import profile_uri
from nightreign_overlay.plugins.p2p_latency.models import P2PPeer, P2PStatus
from nightreign_overlay.plugins.p2p_latency.playtime import PlaytimeResult
from nightreign_overlay.ui.components.steam_profile import open_steam_profile
from tests.plugins.test_p2p_latency import _window
from tests.plugins.test_p2p_latency import plugin as plugin
from tests.support.qt import process_events

TARGET = "76561198000000002"
OTHER = "76561198000000003"


def peers(name="<b>A teammate</b>", target=TARGET):
    return [P2PPeer(target, name, 30, 0.99, "messages", "connected")]


@pytest.mark.parametrize(
    "target", ["abc", "1", "76561198000000002/", "７６５６１１９８００００００００２", "00000000000000000"]
)
def test_profile_uri_rejects_invalid_input(target):
    assert profile_uri(target) is None


def test_profile_uses_steam_internal_uri(monkeypatch):
    opened = []
    monkeypatch.setattr(
        "nightreign_overlay.ui.components.steam_profile.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    assert open_steam_profile(TARGET)
    assert not open_steam_profile("bad")
    assert opened == [f"steam://url/SteamIDPage/{TARGET}"]


@pytest.fixture
def window(plugin, monkeypatch):
    opened = []
    monkeypatch.setattr("nightreign_overlay.plugins.p2p_latency.overlay.open_steam_profile", opened.append)
    widget = _window(plugin)
    widget.set_status(P2PStatus("steam_ready", "ready"))
    widget.set_peers(peers())
    process_events()
    widget.opened = opened
    return widget


def test_refresh_between_press_and_release_keeps_target(window):
    label = window._rows[TARGET][0]
    assert label.textFormat() == Qt.TextFormat.PlainText
    QTest.mousePress(label, Qt.MouseButton.LeftButton)
    window.set_peers(peers("renamed"))
    window.set_playtimes({TARGET: PlaytimeResult("available", 120)})
    assert window._rows[TARGET][0] is label
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton)
    assert not window.opened
    process_events()
    assert window.opened == [TARGET]


def test_departed_or_replaced_target_is_not_opened_from_queued_click(window):
    label = window._rows[TARGET][0]
    QTest.mouseClick(label, Qt.MouseButton.LeftButton)
    window.set_peers(peers("new", OTHER))
    process_events()
    assert not window.opened


@pytest.mark.parametrize("locked", [False, True])
def test_drag_and_right_click_never_open_profile(window, locked):
    window.config.input_mode.set("locked" if locked else "normal")
    label = window._rows[TARGET][0]
    initial = window.pos()
    local = QPointF(label.rect().center())
    point = QPointF(label.mapToGlobal(local.toPoint()))
    label.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            local,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    delta = QPointF(60, 30)
    label.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            local + delta,
            point + delta,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    label.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            local + delta,
            point + delta,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    process_events()
    assert not window.opened
    assert (window.pos() == initial) == locked
    right = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local,
        point,
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    label.mousePressEvent(right)
    assert not right.isAccepted()


def test_playtime_switch_removes_column_and_keeps_name_target(window, plugin):
    label = window._rows[TARGET][0]
    window.set_playtimes({TARGET: PlaytimeResult("unavailable")})
    assert window.peer_grid.itemAtPosition(0, 3).widget().text() == "时长不可用"
    plugin.config.show_playtime.set(False)
    assert window.width() == 240
    assert window.peer_grid.count() == 3
    assert window._rows[TARGET][0] is label
    plugin.config.show_playtime.set(True)
    window.set_playtimes({TARGET: PlaytimeResult("available", 0)})
    assert window.peer_grid.itemAtPosition(0, 3).widget().text() == "0.0 小时"
