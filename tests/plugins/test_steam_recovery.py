"""Migration boundaries: real plugin wiring and file IPC, without Steam mutations."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtWidgets import QWidget

from nightreign_overlay.core.config import ConfigStore
from nightreign_overlay.core.paths import DATA_DIR_ENV
from nightreign_overlay.plugin import PluginKind, PluginManager, SettingsScope
from nightreign_overlay.plugin.context import PluginContext
from nightreign_overlay.plugins.p2p_latency.api import PeerSnapshot
from nightreign_overlay.plugins.p2p_latency.config import P2PConfig
from nightreign_overlay.plugins.p2p_latency.models import parse_helper_message, snapshot_account
from nightreign_overlay.plugins.p2p_latency.plugin import P2PLatencyPlugin, _RecoveryLabel
from nightreign_overlay.plugins.p2p_latency.service import P2PService
from nightreign_overlay.plugins.steam_recovery import identity_bridge as ipc
from nightreign_overlay.plugins.steam_recovery.api import RecoveryApi, RecoveryStatus
from nightreign_overlay.plugins.steam_recovery.match_block import MatchBlockController
from nightreign_overlay.plugins.steam_recovery.paths import identity_directory
from nightreign_overlay.plugins.steam_recovery.plugin import SteamRecoveryPlugin
from nightreign_overlay.ui.components import ConfigSwitchCard
from tests.plugins.test_match_block import ACCOUNT, Bridge, peer
from tests.plugins.test_p2p_latency import plugin as plugin
from tests.support.paths import PROJECT_ROOT

TARGET = peer().steam_id


@pytest.fixture
def recovery(plugin, store, monkeypatch, tmp_path):
    helper = tmp_path / "helper.exe"
    helper.touch()
    launch = Mock(return_value=Mock(poll=Mock(return_value=None)))
    monkeypatch.setattr(ipc, "resolve_helper_path", lambda: helper)
    monkeypatch.setattr(ipc, "_launch_worker", launch)
    root = PROJECT_ROOT / "src/nightreign_overlay/plugins/steam_recovery"
    context = PluginContext(
        "steam_recovery", root, store, plugin.ctx._translator, plugin.ctx.services, plugin.ctx._events
    )
    instance = SteamRecoveryPlugin(context)
    instance.on_load()
    instance.on_activate()
    yield instance, launch
    context.release()


def test_default_off_keeps_recovery_available_without_starting_steam(recovery, plugin):
    instance, launch = recovery
    assert instance.manifest.kind == PluginKind.INFRASTRUCTURE
    assert instance.manifest.settings_scope == SettingsScope.HIDDEN
    assert not plugin.config.auto_block.value
    plugin.ctx.publish(PeerSnapshot((peer(),), ACCOUNT, True))
    instance._controller.tick()
    assert instance._controller.peers[TARGET] == peer()
    assert not instance._controller.enabled
    assert not launch.called
    assert plugin.ctx.services.get(RecoveryApi) is instance


def test_manager_starts_recovery_when_latency_is_disabled(plugin, store, monkeypatch):
    launch = Mock()
    monkeypatch.setattr(ipc, "_launch_worker", launch)
    manager = PluginManager(store, plugin.ctx._translator, plugin.ctx.services, plugin.ctx._events)
    manager.register(SteamRecoveryPlugin)
    manager.register(P2PLatencyPlugin)
    manager.load_all()
    manager._config.enabled.set({"p2p_latency": False})
    manager.start()
    try:
        assert manager.is_active("steam_recovery")
        assert not manager.is_active("p2p_latency")
        assert plugin.ctx.services.get(RecoveryApi) is not None
        assert not launch.called
    finally:
        manager.shutdown()
    assert plugin.ctx.services.get(RecoveryApi) is None


def test_switch_persists_but_only_active_latency_authorizes_holds(plugin, store, monkeypatch):
    recovery = Mock(spec=RecoveryApi)
    recovery.status = RecoveryStatus()
    plugin.ctx.services.register(RecoveryApi, recovery)
    monkeypatch.setattr("nightreign_overlay.plugins.p2p_latency.plugin.sys.platform", "darwin")
    monkeypatch.setattr(P2PService, "start", lambda _self: None)
    monkeypatch.setattr(P2PService, "stop", lambda _self: None)
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    cards = {card.item.key: card for card in panel.findChildren(ConfigSwitchCard)}
    assert "auto_block" in cards
    plugin.config.auto_block.set(True)
    recovery.set_enabled.assert_called_with(False)
    store.flush()
    reloaded = ConfigStore(store.path)
    assert reloaded.bind(P2PConfig, "plugins.p2p_latency").auto_block.value
    plugin.on_activate()
    recovery.set_enabled.assert_called_with(True)
    plugin.ctx.release()
    recovery.set_enabled.assert_called_with(False)
    assert plugin.ctx.services.get(RecoveryApi) is recovery
    parent.deleteLater()
    reloaded.deleteLater()


@pytest.mark.parametrize("contents", ['{"recovery_needed":true}', "{"])
def test_pending_or_corrupt_journal_starts_recovery_even_when_switch_off(recovery, contents, monkeypatch):
    instance, launch = recovery
    bridge = instance._controller.bridges[0]
    path = bridge._root / f"journal-{ACCOUNT}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    bridge._poll()
    assert launch.call_count == 1
    assert not bridge._requests_enabled
    assert not bridge.begin(TARGET)
    worker = bridge._worker
    instance._stop()
    assert not worker.terminate.called and not worker.kill.called


def test_completed_journal_does_not_start_a_worker(recovery):
    instance, launch = recovery
    bridge = instance._controller.bridges[0]
    ipc._write_json(bridge._root / f"journal-{ACCOUNT}.json", {"recovery_needed": False})
    bridge._poll()
    assert not launch.called


def test_pending_query_covers_journals_before_status_and_ignores_other_accounts(recovery):
    instance, _ = recovery
    path = instance._controller.bridges[0]._root / f"journal-{ACCOUNT}.json"
    record = dict(account=ACCOUNT, target=TARGET, recovery_needed=True)
    ipc._write_json(path, record)
    assert instance.pending(ACCOUNT, TARGET)
    assert not instance.pending(TARGET, ACCOUNT)
    ipc._write_json(path, dict(record, recovery_needed=False))
    assert not instance.pending(ACCOUNT, TARGET)
    path.write_text("{", encoding="utf-8")
    assert instance.pending(ACCOUNT, TARGET)


def test_unverified_roster_cannot_block_and_account_change_restores(recovery):
    instance, _ = recovery
    instance._stop()
    bridges = [Bridge(), Bridge()]
    controller = MatchBlockController(bridges=bridges, legacy=Bridge())
    instance._controller = controller
    controller.set_enabled(True)
    instance._snapshot(PeerSnapshot((peer(),), ACCOUNT))
    assert not bridges[0].begins
    instance._snapshot(PeerSnapshot((peer(),), ACCOUNT, True))
    assert bridges[0].begins == [TARGET]
    assert bridges[0].expected_account == ACCOUNT
    instance._snapshot(PeerSnapshot((), peer(2).steam_id, True))
    assert bridges[0].restores > 0
    assert not controller.peers


def test_display_account_fallback_does_not_authorize_native_mutations(plugin, monkeypatch):
    events = []
    plugin.ctx.subscribe(PeerSnapshot, events.append)
    monkeypatch.setattr(
        "nightreign_overlay.plugins.p2p_latency.plugin.current_steam_account", lambda: ACCOUNT
    )
    plugin._service = SimpleNamespace(account="")
    plugin._publish_snapshot((peer(),))
    assert events[-1].account == ACCOUNT and not events[-1].verified_account
    plugin._service.account = ACCOUNT
    plugin._publish_snapshot((peer(),))
    assert events[-1].verified_account
    plugin._service = None


@pytest.mark.parametrize("relationship", [True, "0", -1, 9])
def test_untrusted_relationship_is_not_treated_as_nonfriend(relationship):
    raw = dict(steam_id=TARGET, name="Peer", api="messages", state="connected", relationship=relationship)
    with pytest.raises(ValueError):
        parse_helper_message(json.dumps(dict(type="snapshot", peers=[raw])))


def test_older_helper_can_display_peers_without_authorizing_blocks():
    raw = dict(steam_id=TARGET, name="Peer", api="messages", state="connected", ping_ms=30)
    line = json.dumps(dict(type="snapshot", peers=[raw]))
    assert parse_helper_message(line)[1][0].relationship is None
    assert snapshot_account(line) == ""
    with pytest.raises(ValueError):
        snapshot_account(json.dumps(dict(type="snapshot", account="not a Steam ID", peers=[])))


def test_data_directory_override_isolates_legacy_journals(monkeypatch, tmp_path):
    isolated = identity_directory()
    assert isolated == tmp_path / "data/identity"
    monkeypatch.delenv(DATA_DIR_ENV)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert identity_directory() == tmp_path / "local/NightreignOverlayHelper/identity"


def test_status_stays_readable_after_latency_is_disabled(plugin):
    recovery = Mock(spec=RecoveryApi)
    recovery.status = RecoveryStatus("recovery_pending")
    plugin.ctx.services.register(RecoveryApi, recovery)
    parent = QWidget()
    panel = plugin.create_settings_widget(parent)
    label = panel.findChild(_RecoveryLabel)
    assert label.text() == plugin.ctx.tr("block.summary.recovery_pending")
    assert plugin._service is None
    recovery.status = RecoveryStatus("disabled")
    label.refresh()
    assert label.text() == plugin.ctx.tr("block.summary.disabled")
    parent.deleteLater()
