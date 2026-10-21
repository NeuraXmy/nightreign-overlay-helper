"""Offline production policy tests: no Steam, account or native processes."""

import unittest
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from nightreign_overlay.plugins.p2p_latency.models import P2PPeer, parse_helper_message
from nightreign_overlay.plugins.steam_recovery.match_block import MatchBlockController

pytestmark = pytest.mark.usefixtures("qapp")
ACCOUNT = "76561198049468922"


class Bridge:
    def __init__(self):
        self.status = dict(state="idle", message="", accepts_begin=True)
        self._pending = None
        self.hold_target = ""
        self.begins = []
        self.restores = 0
        self.start = Mock()
        self.stop = Mock()

    def set_requests_enabled(self, enabled):
        pass

    def begin(self, target):
        self.begins.append(target)
        self._pending = "transaction"
        self.status.update(state="preparing", accepts_begin=False)
        return True

    def restore(self):
        self.hold_target = ""
        if self._pending:
            self.restores += 1
            self.status.update(state="restoring", accepts_begin=False)

    @property
    def pending(self):
        return self._pending is not None

    def authorize_hold(self, target):
        self.hold_target = target


def peer(n=1, relationship=0):
    return P2PPeer(str(76561198049468922 + n), "Anonymous", 42, 1.0, "legacy", "connected", relationship)


class MatchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.bridges = [Bridge(), Bridge()]
        self.legacy = Bridge()
        self.controller = MatchBlockController(
            bridges=self.bridges, legacy=self.legacy, clock=lambda: self.now
        )
        self.controller.set_account(ACCOUNT)
        self.controller.set_enabled(True)

    def feed(self, peers, seconds=1):
        self.now += seconds
        self.controller.set_peers(peers)

    def opening(self, peers):
        self.feed(peers)
        self.feed(peers, 6)

    def continuous(self, players, seconds=10):
        for _ in range(seconds):
            self.feed(players)

    def test_ping_ready_peer_starts_without_day1(self):
        self.feed([peer()])
        self.assertEqual(self.bridges[0].begins, [peer().steam_id])

    def test_prepare_timeout_retries_after_backoff_and_backoff_grows(self):
        self.feed([peer()])
        bridge = self.bridges[0]
        for delay in (30, 60, 120, 180):
            bridge._pending = None
            bridge.status.update(state="error", diagnostic_code="page_timeout", accepts_begin=True)
            self.controller.tick()
            count = len(bridge.begins)
            self.feed([peer()], delay - 1)
            self.assertEqual(len(bridge.begins), count)
            self.feed([peer()])
            self.assertEqual(len(bridge.begins), count + 1)

    def test_real_bridge_result_is_not_lost_when_idle_heartbeat_follows(self):
        self.check_real_bridge_retry("error", "page_timeout")

    def test_compensated_block_failure_survives_idle_heartbeat_and_retries(self):
        self.check_real_bridge_retry("restored", "block_unconfirmed")

    def check_real_bridge_retry(self, state, code):
        from datetime import datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from nightreign_overlay.plugins.steam_recovery import identity_bridge as ipc

        with (
            TemporaryDirectory() as directory,
            patch.object(ipc, "identity_directory", return_value=Path(directory)),
            patch.object(ipc, "_launch_worker"),
        ):
            bridges = [ipc.IdentityBridge(slot=i) for i in (0, 1)]
            controller = MatchBlockController(bridges=bridges, legacy=Bridge(), clock=lambda: self.now)
            try:
                for bridge in bridges:
                    ipc._write_json(
                        bridge._root / "status.json",
                        dict(
                            state="idle",
                            message="test",
                            accepts_begin=True,
                            steam_lifecycle=ipc._MATCH_LIFECYCLE,
                            updated_at=datetime.now(UTC).isoformat(),
                        ),
                    )
                    bridge.expected_account = ACCOUNT
                    bridge.set_requests_enabled(True)
                    bridge.start()
                    bridge._timer.stop()
                controller.set_account(ACCOUNT)
                controller.set_enabled(True)
                controller.set_peers([peer()])
                first = bridges[0]._pending
                self.assertIsNotNone(first)
                (bridges[0]._root / "requests" / f"{first}.json").unlink()
                ipc._write_json(
                    bridges[0]._root / "results" / f"{first}.json",
                    dict(
                        state=state,
                        target=peer().steam_id,
                        transaction=first,
                        message="timeout",
                        diagnostic_code=code,
                    ),
                )
                # The native status has already returned to idle; completion
                # must still arm retry before its diagnostic gets overwritten.
                bridges[0]._poll()
                self.assertIn(peer().steam_id, controller.retry_at)
                self.assertFalse(controller.assigned)
                self.now += 30
                controller.set_peers([peer()])
                pending = [b._pending for b in bridges if b.pending]
                self.assertEqual(len(pending), 1)
                self.assertNotEqual(pending[0], first)
                self.assertEqual(len(controller.assigned), 1, "reentrant preparation assigned target twice")
            finally:
                controller.stop()

    def test_block_retry_waits_for_verified_restoration_then_backs_off(self):
        self.feed([peer()])
        bridge = self.bridges[0]
        for delay in (30, 60, 120, 180):
            bridge.status.update(state="recovery_pending", diagnostic_code="block_unconfirmed")
            count = len(bridge.begins)
            self.feed([peer()], 600)
            self.assertEqual(len(bridge.begins), count)
            self.assertFalse(self.controller.retry_at)
            bridge._pending = None
            bridge.status.update(state="restored", accepts_begin=True)
            self.controller.tick()
            self.assertIn(peer().steam_id, self.controller.retry_at)
            self.assertEqual(self.controller.peer_statuses[peer().steam_id].state, "retry_wait")
            self.feed([peer()], delay - 1)
            self.assertEqual(len(bridge.begins), count)
            self.feed([peer()])
            self.assertEqual(len(bridge.begins), count + 1)

    def test_compensated_retry_still_requires_nonfriend_ping_and_enabled_setting(self):
        from dataclasses import replace

        self.feed([peer()])
        bridge = self.bridges[0]
        bridge._pending = None
        bridge.status.update(state="restored", diagnostic_code="block_unconfirmed", accepts_begin=True)
        self.controller.tick()
        self.assertIn(peer().steam_id, self.controller.retry_at)
        self.feed([peer(1, 3)], 30)
        self.feed([replace(peer(), ping_ms=None)])
        self.controller.set_enabled(False)
        self.feed([peer()])
        self.assertEqual(len(bridge.begins), 1)
        self.controller.set_enabled(True)
        self.assertEqual(len(bridge.begins), 2)

    def test_transient_real_lease_write_failure_does_not_revoke_blocked_target(self):
        from datetime import datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from nightreign_overlay.plugins.steam_recovery import identity_bridge as ipc

        with (
            TemporaryDirectory() as directory,
            patch.object(ipc, "identity_directory", return_value=Path(directory)),
            patch.object(ipc, "_launch_worker"),
        ):
            bridges = [ipc.IdentityBridge(slot=i) for i in (0, 1)]
            controller = MatchBlockController(bridges=bridges, legacy=Bridge(), clock=lambda: self.now)
            try:
                for bridge in bridges:
                    ipc._write_json(
                        bridge._root / "status.json",
                        dict(
                            state="idle",
                            message="test",
                            accepts_begin=True,
                            steam_lifecycle=ipc._MATCH_LIFECYCLE,
                            updated_at=datetime.now(UTC).isoformat(),
                        ),
                    )
                    bridge.expected_account = ACCOUNT
                    bridge.set_requests_enabled(True)
                    bridge.start()
                    bridge._timer.stop()
                controller.set_account(ACCOUNT)
                controller.set_enabled(True)
                controller.set_peers([peer()])
                bridge = bridges[0]
                transaction = bridge._pending
                ipc._write_json(
                    bridge._root / "status.json",
                    dict(
                        state="blocked",
                        message="test",
                        accepts_begin=False,
                        target=peer().steam_id,
                        transaction=transaction,
                        steam_lifecycle=ipc._MATCH_LIFECYCLE,
                        updated_at=datetime.now(UTC).isoformat(),
                    ),
                )
                bridge._poll()
                bridge._last_lease -= 2
                with patch.object(ipc, "_write_json", side_effect=OSError("temporarily locked")):
                    bridge._poll()
                self.assertEqual(bridge.status["state"], "blocked")
                self.assertEqual(bridge.hold_target, peer().steam_id)
                self.assertEqual(bridge._poll_reason, "lease_write_grace")
                bridge._poll()
                lease = ipc._read_json(bridge._root / "clients" / (bridge._client + ".json"))
                self.assertEqual(lease["hold_target"], peer().steam_id)
                self.assertFalse((bridge._root / f"restore-{transaction}.json").exists())
            finally:
                controller.stop()

    def test_friend_or_departure_cancels_retry_and_mutation_outcomes_never_retry(self):
        self.feed([peer()])
        bridge = self.bridges[0]
        bridge._pending = None
        bridge.status.update(state="error", diagnostic_code="page_controls", accepts_begin=True)
        self.controller.tick()
        self.feed([peer(1, 3)], 31)
        self.assertEqual(len(bridge.begins), 1)
        self.feed([])
        self.assertFalse(self.controller.retry_at)
        self.feed([peer()])
        bridge._pending = None
        bridge.status.update(state="restored", diagnostic_code="", accepts_begin=True)
        self.controller.tick()
        self.feed([peer()], 200)
        self.assertEqual(len(bridge.begins), 2)

    def test_two_failures_retry_independently_and_toggle_off_stops_retry(self):
        self.feed([peer(1), peer(2)])
        for bridge in self.bridges:
            bridge._pending = None
            bridge.status.update(state="error", diagnostic_code="browser_start", accepts_begin=True)
        self.controller.tick()
        self.controller.set_enabled(False)
        self.feed([peer(1), peer(2)], 31)
        self.assertEqual([len(b.begins) for b in self.bridges], [1, 1])
        self.controller.set_account(ACCOUNT)
        self.controller.set_enabled(True)
        self.assertEqual([len(b.begins) for b in self.bridges], [2, 2])

    def test_missing_or_invalid_ping_waits_then_valid_ping_starts(self):
        from dataclasses import replace

        for ping in (None, -1, True):
            self.feed([replace(peer(), ping_ms=ping)])
            self.assertFalse(any(b.begins for b in self.bridges))
        self.feed([replace(peer(), ping_ms=0)])
        self.assertEqual(self.bridges[0].begins, [peer().steam_id])

    def test_three_expeditions_release_completed_slots_with_real_file_bridge(self):
        from datetime import datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from nightreign_overlay.plugins.steam_recovery import identity_bridge as ipc

        with (
            TemporaryDirectory(prefix="nr-match-rounds-") as directory,
            patch.object(ipc, "identity_directory", return_value=Path(directory)),
            patch.object(ipc, "_launch_worker") as launch,
        ):
            bridges = [ipc.IdentityBridge(slot=i) for i in (0, 1)]
            controller = MatchBlockController(bridges=bridges, legacy=Bridge(), clock=lambda: self.now)

            def status(bridge, state, transaction="", target=""):
                ipc._write_json(
                    bridge._root / "status.json",
                    dict(
                        state=state,
                        transaction=transaction,
                        target=target,
                        message="test",
                        accepts_begin=state in {"idle", "restored", "error"},
                        steam_lifecycle=ipc._MATCH_LIFECYCLE,
                        updated_at=datetime.now(UTC).isoformat(),
                    ),
                )
                bridge._poll()

            try:
                for bridge in bridges:
                    status(bridge, "idle")
                    bridge.expected_account = ACCOUNT
                    bridge.set_requests_enabled(True)
                    bridge.start()
                    bridge._timer.stop()
                controller.set_account(ACCOUNT)
                controller.set_enabled(True)
                # Changed opponents, then rematch with the same opponents.
                for players in ([peer(1), peer(2)], [peer(3), peer(4)], [peer(3), peer(4)]):
                    self.now += 600
                    controller.set_peers(players)
                    self.now += 6
                    controller.set_peers(players)
                    self.assertEqual(len(controller.assigned), 2)
                    transactions = [b._pending for b in bridges]
                    self.assertTrue(all(transactions), "next expedition failed to submit new requests")
                    for bridge, transaction, player in zip(bridges, transactions, players, strict=True):
                        status(bridge, "blocked", transaction, player.steam_id)
                    controller.set_peers([])
                    for _ in range(10):
                        self.now += 1
                        controller.set_peers([])
                    for bridge, transaction, player in zip(bridges, transactions, players, strict=True):
                        self.assertTrue((bridge._root / f"restore-{transaction}.json").exists())
                        # Native completion removes the restore marker, retains
                        # the transaction in status, and writes a terminal result.
                        (bridge._root / f"restore-{transaction}.json").unlink()
                        ipc._write_json(
                            bridge._root / "results" / f"{transaction}.json",
                            dict(
                                state="restored",
                                target=player.steam_id,
                                transaction=transaction,
                                message="done",
                            ),
                        )
                        status(bridge, "restored", transaction, player.steam_id)
                    controller.tick()
                    self.assertFalse(controller.assigned, "completed departed targets retained")
                    for bridge, transaction in zip(bridges, transactions, strict=True):
                        self.assertEqual(bridge.status["state"], "restored")
                        self.assertFalse(
                            (bridge._root / f"restore-{transaction}.json").exists(),
                            "completed restore reissued",
                        )
                launch.assert_not_called()
            finally:
                controller.stop()

    def test_two_nonfriends_hold_in_independent_slots(self):
        self.opening([peer(1), peer(2)])
        self.assertEqual([b.begins for b in self.bridges], [[peer(1).steam_id], [peer(2).steam_id]])
        self.feed([peer(1, 5), peer(2, 5)], 600)
        self.assertEqual([b.restores for b in self.bridges], [0, 0])

    def test_second_preparation_can_retry_past_opening_without_restarting_first(self):
        self.opening([peer(1), peer(2)])
        self.bridges[0].status.update(state="blocked")
        for _ in range(60):
            self.feed([peer(1, 5), peer(2)])
        self.assertEqual(self.bridges[1].status["state"], "preparing")
        self.assertEqual(self.bridges[1].hold_target, peer(2).steam_id)
        self.assertEqual([b.restores for b in self.bridges], [0, 0])
        self.assertEqual([len(b.begins) for b in self.bridges], [1, 1])
        self.bridges[1].status.update(state="blocked")
        self.feed([peer(1, 5), peer(2, 5)])
        self.assertEqual(len(self.controller.assigned), 2)
        self.feed([peer(1, 5)])
        self.continuous([peer(1, 5)])
        self.assertEqual([b.restores for b in self.bridges], [0, 1])

    def test_friend_unknown_and_preblocked_are_excluded(self):
        for relationship in (None, 1, 2, 3, 4, 5, 6):
            self.opening([peer(1, relationship)])
            self.assertFalse(any(b.begins for b in self.bridges))
            self.now += 200

    def test_longstanding_nonfriend_is_processed_once_when_ping_ready(self):
        self.feed([peer()])
        self.feed([peer()], 130)
        self.feed([peer()], 6)
        self.assertEqual(len(self.bridges[0].begins), 1)

    def test_departed_peer_only_is_restored(self):
        self.opening([peer(1), peer(2)])
        self.feed([peer(2)])
        self.continuous([peer(2)])
        self.assertEqual([b.restores for b in self.bridges], [1, 0])
        self.assertEqual(self.bridges[0].hold_target, "")

    def test_staying_in_room_across_day1_does_not_restore_or_double_block(self):
        self.opening([peer()])
        self.feed([peer(1, 5)], 600)
        self.feed([peer(1, 5)], 6)
        self.assertEqual(self.bridges[0].restores, 0)
        self.assertEqual(self.bridges[0].begins, [peer().steam_id])

    def test_stale_snapshot_holds_for_grace_then_restores(self):
        self.opening([peer()])
        self.now += 6
        self.controller.tick()
        self.assertEqual(self.bridges[0].restores, 0)
        self.now += 24
        self.controller.tick()
        self.assertEqual(self.bridges[0].restores, 1)

    def test_helper_failure_stops_new_block_but_preserves_existing_hold(self):
        self.opening([peer()])
        last = self.controller.last_snapshot
        self.controller.set_status(SimpleNamespace(state="runtime_error"))
        self.assertEqual(self.bridges[0].restores, 0)
        self.assertFalse(self.controller.snapshot_valid)
        self.assertEqual(self.controller.last_snapshot, last)
        self.now += 15
        self.controller.tick()
        self.assertEqual(self.bridges[0].hold_target, peer().steam_id)
        self.feed([peer(1, 5)])
        self.assertEqual(self.bridges[0].restores, 0)

    def test_brief_empty_reconnection_and_missing_ping_do_not_restore(self):
        from dataclasses import replace

        self.opening([peer()])
        self.feed([])
        self.feed([], 8)
        self.assertEqual(self.bridges[0].restores, 0)
        self.feed([replace(peer(1, 5), state="connecting", ping_ms=None)])
        self.feed([replace(peer(1, 5), state="connecting", ping_ms=None)], 15)
        self.assertEqual(self.bridges[0].restores, 0)
        self.assertEqual(len(self.bridges[0].begins), 1)

    def test_departure_needs_continuous_fresh_absence_and_restarts_after_gap(self):
        self.opening([peer()])
        self.feed([])
        self.now += 8
        self.controller.tick()
        self.feed([])
        self.assertEqual(self.bridges[0].restores, 0)
        self.continuous([])
        self.assertEqual(self.bridges[0].restores, 1)

    def test_snapshot_gap_before_stale_timer_cannot_confirm_departure(self):
        self.opening([peer()])
        self.feed([])
        # No tick during the gap: simulate the Qt GUI event loop being paused.
        self.feed([], 10)
        self.assertEqual(self.bridges[0].restores, 0)
        self.continuous([])
        self.assertEqual(self.bridges[0].restores, 1)

    def test_helper_restart_waiting_state_is_not_real_game_exit(self):
        self.opening([peer()])
        for state in ("helper_restarting", "helper_started", "waiting_for_game"):
            self.controller.set_status(SimpleNamespace(state=state))
        self.assertEqual(self.bridges[0].restores, 0)
        self.controller.set_status(SimpleNamespace(state="game_exited"))
        self.assertEqual(self.bridges[0].restores, 1)

    def test_disabled_waits_and_enabling_midgame_processes_fresh_peers(self):
        self.controller.set_enabled(False)
        self.feed([peer()])
        self.assertFalse(self.bridges[0].begins)
        self.controller.set_account(ACCOUNT)
        self.controller.set_enabled(True)
        self.assertEqual(self.bridges[0].begins, [peer().steam_id])

    def test_late_joiner_is_processed_when_ping_is_ready(self):
        self.feed([peer()], 200)
        self.assertEqual(self.bridges[0].begins, [peer().steam_id])

    def test_recovery_pending_blocks_new_operations(self):
        self.legacy.status.update(state="recovery_pending")
        self.opening([peer()])
        self.assertFalse(any(b.begins for b in self.bridges))

    def test_recovered_target_not_reblocked_this_run(self):
        self.opening([peer()])
        self.bridges[0]._pending = None
        self.bridges[0].status.update(state="restored", accepts_begin=True)
        self.feed([peer()])
        self.assertEqual(len(self.bridges[0].begins), 1)
        self.assertFalse(self.bridges[1].begins)

    def test_returning_same_peer_can_start_after_departure_recovery_finishes(self):
        self.feed([peer()])
        self.feed([])
        self.continuous([])
        self.feed([peer()])
        self.assertEqual(len(self.bridges[0].begins), 1)
        self.bridges[0]._pending = None
        self.bridges[0].status.update(state="restored", accepts_begin=True)
        self.feed([peer()])
        self.assertEqual(len(self.bridges[0].begins), 2)

    def test_shutdown_keeps_native_recovery_owner(self):
        self.opening([peer()])
        self.controller.stop()
        self.assertEqual(self.bridges[0].restores, 1)
        for b in [self.legacy, *self.bridges]:
            b.stop.assert_called_once()

    def test_missing_relationship_in_old_helper_is_unknown(self):
        import json

        data = dict(
            type="snapshot", peers=[dict(steam_id=peer().steam_id, name="x", api="legacy", state="connected")]
        )
        self.assertIsNone(parse_helper_message(json.dumps(data))[1][0].relationship)
        data["peers"][0]["relationship"] = True
        with self.assertRaises(ValueError):
            parse_helper_message(json.dumps(data))
