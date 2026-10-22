from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel

from nightreign_overlay.core.i18n import Translator
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.commendation.config import CommendationConfig
from nightreign_overlay.plugins.commendation.history import cooldown_state
from nightreign_overlay.plugins.commendation.plugin import CommendationPlugin, _CommentCard
from nightreign_overlay.plugins.commendation.service import CommendationService
from nightreign_overlay.plugins.commendation.session import ExpeditionRoster
from nightreign_overlay.plugins.day_timer.api import DayStarted
from nightreign_overlay.plugins.p2p_latency.api import P2PPeer, P2PStateChanged, P2PStatus, PeerSnapshot
from tests.plugins.test_p2p_latency import plugin as plugin
from tests.support.paths import PROJECT_ROOT
from tests.support.qt import process_events

ACCOUNT, TARGET, OTHER = "76561198000000001", "76561198000000002", "76561198000000003"


def peer(target=TARGET):
    return P2PPeer(target, "Teammate " + target[-1], 35, 0.95, "messages", "connected")


def test_lobby_does_not_show_and_departure_does_not_wait_for_friend():
    roster = ExpeditionRoster()
    assert roster.snapshot((peer(), peer(OTHER)), ACCOUNT, 0) == []
    assert roster.snapshot((), ACCOUNT, 4) == []
    roster.snapshot((peer(), peer(OTHER)), ACCOUNT, 5)
    assert roster.start(5)
    assert roster.snapshot((peer(OTHER),), ACCOUNT, 6) == []
    left = roster.snapshot((peer(OTHER),), ACCOUNT, 9)
    assert [p.steam_id for p in left] == [TARGET]
    assert roster.snapshot((peer(OTHER),), ACCOUNT, 10) == []
    roster.snapshot((), ACCOUNT, 11)
    assert [p.steam_id for p in roster.snapshot((), ACCOUNT, 14)] == [OTHER]


def test_snapshot_gap_and_reconnect_restart_confirmation():
    roster = ExpeditionRoster()
    roster.snapshot((peer(),), ACCOUNT, 0)
    roster.start(0)
    roster.snapshot((), ACCOUNT, 1)
    assert roster.snapshot((), ACCOUNT, 8) == []  # seven seconds of silence
    assert roster.snapshot((peer(),), ACCOUNT, 9) == []
    roster.snapshot((), ACCOUNT, 10)
    roster.pause()  # helper failure is not a departure
    assert roster.snapshot((), ACCOUNT, 14) == []
    assert len(roster.snapshot((), ACCOUNT, 17)) == 1


def test_day_one_before_first_peer_and_second_match():
    roster = ExpeditionRoster()
    roster.start(0)
    roster.snapshot((peer(),), ACCOUNT, 1)
    roster.snapshot((), ACCOUNT, 2)
    assert len(roster.snapshot((), ACCOUNT, 5)) == 1
    assert not roster.start(6)  # duplicate OCR
    roster.start(180)
    roster.snapshot((peer(OTHER),), ACCOUNT, 181)
    roster.snapshot((), ACCOUNT, 182)
    assert [p.steam_id for p in roster.snapshot((), ACCOUNT, 185)] == [OTHER]


def test_account_switch_discards_previous_roster():
    roster = ExpeditionRoster()
    roster.snapshot((peer(),), ACCOUNT, 0)
    roster.start(0)
    assert roster.snapshot((), OTHER, 1) == []
    assert not roster.roster and not roster.tracking


def test_continuous_day_one_banner_only_starts_one_roster():
    roster = ExpeditionRoster()
    roster.snapshot((peer(),), ACCOUNT, 0)
    assert roster.start(0)
    roster.snapshot((), ACCOUNT, 1)
    assert len(roster.snapshot((), ACCOUNT, 4)) == 1
    # Repeated hits refresh the debounce, even if a banner stays visible longer.
    for now in range(6, 132, 2):
        assert not roster.start(now)
        assert roster.reported == {TARGET}
    assert roster.start(145)


def test_finished_roster_can_start_again_within_same_banner_interval():
    roster = ExpeditionRoster()
    roster.snapshot((peer(),), ACCOUNT, 0)
    assert roster.start(0)
    assert len(roster.finish()) == 1
    assert roster.start(2)
    roster.snapshot((peer(OTHER),), ACCOUNT, 3)
    roster.snapshot((), ACCOUNT, 4)
    assert [p.steam_id for p in roster.snapshot((), ACCOUNT, 7)] == [OTHER]


@pytest.fixture
def service(store, tmp_path):
    now, account = [0.0], [ACCOUNT]
    result = CommendationService(
        store.bind(CommendationConfig, "plugins.commendation"),
        clock=lambda: now[0],
        account_reader=lambda: account[0],
        history=tmp_path / "history",
    )
    result.now, result.account = now, account
    result.rows = []
    result.rowsChanged.connect(lambda rows: setattr(result, "rows", rows))
    yield result
    result.stop()
    result.deleteLater()


def open_review(service):
    service.on_snapshot(PeerSnapshot((peer(), peer(OTHER)), ACCOUNT))
    service.on_day_started(DayStarted(1))
    service.now[0] = 1
    service.on_snapshot(PeerSnapshot((peer(OTHER),), ACCOUNT))
    service.now[0] = 4
    service.on_snapshot(PeerSnapshot((peer(OTHER),), ACCOUNT))


def test_rows_expire_without_refresh_extending_deadline(service):
    open_review(service)
    assert [row["steam_id"] for row in service.rows] == [TARGET]
    assert service.rows[0]["enabled"]
    service.now[0] = 100
    service.tick()
    service.now[0] = 124
    service.tick()
    assert service.rows == []
    service.show_recent()
    assert len(service.rows) == 2
    service.config.close_seconds.set(10)
    service.now[0] = 134
    service.tick()
    assert service.rows == []


def test_game_exit_opens_only_not_yet_reported_players(service):
    open_review(service)
    service.on_status(P2PStateChanged(P2PStatus("helper_restarting", "failure")))
    assert len(service.rows) == 1
    service.on_status(P2PStateChanged(P2PStatus("game_exited", "ended")))
    assert {row["steam_id"] for row in service.rows} == {TARGET, OTHER}
    assert not service.roster.tracking


@pytest.mark.parametrize("keep_friend", [False, True])
@pytest.mark.parametrize("same_teammate", [False, True])
def test_fast_next_match_replaces_roster_and_reports_each_departure(service, keep_friend, same_teammate):
    open_review(service)
    retained = (peer(OTHER),) if keep_friend else ()
    service.now[0] = 5
    service.on_snapshot(PeerSnapshot(retained, ACCOUNT))
    service.now[0] = 8
    service.on_snapshot(PeerSnapshot(retained, ACCOUNT))
    new_target = TARGET if same_teammate else "76561198000000004"
    next_peers = (peer(new_target), *retained)
    service.now[0] = 89
    service.on_snapshot(PeerSnapshot(next_peers, ACCOUNT))
    service.now[0] = 90
    service.on_day_started(DayStarted(1))
    assert service.rows == []
    assert set(service.roster.roster) == {p.steam_id for p in next_peers}
    service.now[0] = 91
    service.on_snapshot(PeerSnapshot(retained, ACCOUNT))
    service.now[0] = 94
    service.on_snapshot(PeerSnapshot(retained, ACCOUNT))
    assert [row["steam_id"] for row in service.rows] == [new_target]


def test_new_match_dismisses_reviews_and_account_switch_disables_sending(service):
    open_review(service)
    service.account[0] = OTHER
    service.tick()
    assert not service.rows[0]["enabled"]
    assert service.rows[0]["state"] == "account_changed"
    service.account[0] = ACCOUNT
    service.now[0] = 200
    service.on_day_started(DayStarted(1))
    assert service.rows == []


@pytest.mark.parametrize(
    ("state", "expected"),
    [("sent", "cooldown"), ("sending", "unknown"), ("unknown", "unknown"), ("rejected", "retry_later")],
)
def test_persisted_account_target_cooldown(tmp_path, state, expected):
    now = datetime.now(UTC)
    record = dict(
        account=ACCOUNT, target=TARGET, state=state, cooldown_until=(now + timedelta(days=7)).isoformat()
    )
    (tmp_path / f"{ACCOUNT}-{TARGET}.json").write_text(json.dumps(record), encoding="utf-8")
    assert cooldown_state(tmp_path, ACCOUNT, TARGET, now=now) == expected
    assert cooldown_state(tmp_path, OTHER, TARGET, now=now) == "ready"
    assert cooldown_state(tmp_path, ACCOUNT, TARGET, now=now + timedelta(days=8)) == "ready"


@pytest.mark.parametrize("data", ["{", "null", "[]", "{}"])
def test_corrupt_history_disables_posting(tmp_path, data):
    (tmp_path / f"{ACCOUNT}-{TARGET}.json").write_text(data, encoding="utf-8")
    assert cooldown_state(tmp_path, ACCOUNT, TARGET) == "history_error"


def test_only_explicit_click_starts_one_helper_and_pins_account(service, monkeypatch, tmp_path):
    helper = tmp_path / "helper.exe"
    helper.touch()
    monkeypatch.setattr("nightreign_overlay.plugins.commendation.service.helper_path", lambda: helper)
    starts = []
    monkeypatch.setattr(service.process, "start", lambda: starts.append(True))
    open_review(service)
    assert starts == []
    service.send(TARGET)
    service.send(TARGET)
    service.send(OTHER)
    assert starts == [True]
    assert service._request == dict(
        target=TARGET, comment=service.config.comment.value, expected_account=ACCOUNT
    )
    service._response.extend(b'{"state":"unknown"}')
    service._finished()
    service.send(TARGET)
    assert starts == [True]


def test_expired_target_cannot_post(service, monkeypatch):
    open_review(service)
    starts = []
    monkeypatch.setattr(service.process, "start", lambda: starts.append(True))
    service.now[0] = 1000
    service.send(TARGET)
    assert not starts


def test_pending_restore_disables_comment_until_verified_complete(service, monkeypatch, tmp_path):
    helper = tmp_path / "helper.exe"
    helper.touch()
    monkeypatch.setattr("nightreign_overlay.plugins.commendation.service.helper_path", lambda: helper)
    starts, pending = [], [True]
    service.recovery_pending = lambda account, target: account == ACCOUNT and target == TARGET and pending[0]
    monkeypatch.setattr(service.process, "start", lambda: starts.append(True))
    open_review(service)
    assert service.rows[0]["state"] == "restoring"
    service.send(TARGET)
    assert starts == []
    pending[0] = False
    service.tick()
    assert service.rows[0]["enabled"]
    service.send(TARGET)
    assert starts == [True]


def test_separate_plugin_page_window_name_and_like_actions(plugin, store, monkeypatch):
    root = PROJECT_ROOT / "src/nightreign_overlay/plugins/commendation"
    translator = Translator("zh_CN")
    translator.load_dir("commendation", root / "i18n")
    ctx = PluginContext("commendation", root, store, translator, plugin.ctx.services, plugin.ctx._events)
    instance = CommendationPlugin(ctx)
    instance.on_load()
    parent = QWidget()
    panel = instance.create_settings_widget(parent)
    status_section = panel.sectionLayout.itemAt(panel.sectionLayout.count() - 1).widget()
    assert status_section.titleLabel.text() == ctx.tr("settings.status")
    status_label = status_section.findChild(BodyLabel)
    assert status_label.text() == ctx.tr("state.idle")
    card = panel.findChild(_CommentCard)
    card.editor.setText("+rep 配合愉快")
    card.button.click()
    assert instance.config.comment.value == "+rep 配合愉快"
    assert status_label.text() == ctx.tr("state.saved")
    instance.on_activate()
    try:
        window = instance._window
        assert not window.isVisible()
        rows = [dict(steam_id=TARGET, name="A teammate", state="ready", enabled=True)]
        opened, sent = [], []
        monkeypatch.setattr(
            "nightreign_overlay.plugins.commendation.overlay.open_steam_profile", opened.append
        )
        window.commendClicked.connect(sent.append)
        window.set_rows(rows)
        process_events()
        assert window.isVisible()
        name, button, status = window._widgets[TARGET]
        QTest.mouseClick(name, Qt.MouseButton.LeftButton)
        process_events()
        assert opened == [TARGET] and not sent
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        process_events()
        assert sent == [TARGET] and opened == [TARGET]
        assert status.mapTo(window, status.rect().bottomRight()).y() <= window.height()
        window.set_rows([])
        assert not window.isVisible()
    finally:
        ctx.release()
        parent.deleteLater()
        instance.deleteLater()
