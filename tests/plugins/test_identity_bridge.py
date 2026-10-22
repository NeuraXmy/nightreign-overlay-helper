"""Offline file IPC/lifecycle checks; a Steam worker is never launched."""

from __future__ import annotations

import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from nightreign_overlay.plugins.steam_recovery import identity_bridge as ipc

pytestmark = pytest.mark.usefixtures("qapp")
ACCOUNT = "76561198049468922"


class IdentityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nr-identity-ipc-")
        self.root = Path(self.temporary.name)
        self.helper = self.root / "helper.exe"
        self.helper.touch()
        self.process = Mock()
        self.process.poll.return_value = None
        self.launch = Mock(return_value=self.process)
        self.log_info = Mock()
        self.log_warning = Mock()
        self.patches = [
            patch.object(ipc, "identity_directory", return_value=self.root),
            patch.object(ipc, "resolve_helper_path", return_value=self.helper),
            patch.object(ipc, "_launch_worker", self.launch),
            patch.object(ipc, "info", self.log_info),
            patch.object(ipc, "warning", self.log_warning),
        ]
        for item in self.patches:
            item.start()
        self.bridge = ipc.IdentityBridge(slot=0)
        self.bridge.expected_account = ACCOUNT
        self.bridge.set_requests_enabled(True)
        self.root = self.bridge._root
        self.events = []
        self.bridge.changed.connect(self.events.append)

    def tearDown(self):
        self.bridge.stop()
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def status(self, state="idle", transaction="", age=0, lifecycle=ipc._MATCH_LIFECYCLE, **extra):
        value = dict(
            state=state,
            target="76561198049468923",
            transaction=transaction,
            message="test",
            accepts_begin=state in {"idle", "restored"},
            updated_at=(datetime.now(UTC) - timedelta(seconds=age)).isoformat(),
        )
        if lifecycle is not None:
            value["steam_lifecycle"] = lifecycle
        value.update(extra)
        ipc._write_json(self.bridge._root / "status.json", value)

    def begin(self):
        self.status()
        self.bridge.start()
        self.assertTrue(self.bridge.begin("76561198049468923"))
        return self.bridge.status["transaction"]

    def test_start_reconnects_without_relaunching_fresh_worker(self):
        self.status()
        self.bridge.start()
        self.launch.assert_not_called()
        self.assertEqual(self.bridge.status["state"], "idle")
        self.assertTrue((self.root / "clients" / (self.bridge._client + ".json")).is_file())

    def test_preparation_failure_code_survives_result_and_is_logged(self):
        transaction = self.begin()
        ipc._write_json(
            self.root / "results" / f"{transaction}.json",
            dict(
                state="error",
                target="76561198049468923",
                transaction=transaction,
                message="private details",
                diagnostic_code="page_timeout",
            ),
        )
        self.bridge._poll()
        self.assertEqual(self.bridge.status["diagnostic_code"], "page_timeout")
        self.assertFalse(self.bridge.pending)
        logs = str(self.log_info.call_args_list)
        self.assertIn("reason=page_timeout", logs)
        self.assertNotIn("private details", logs)

    def test_untrusted_preparation_code_never_enters_logs(self):
        for code in ("remote text or account", {"bad": "type"}):
            self.status(diagnostic_code=code)
            self.bridge.start()
            self.bridge._poll()
            self.assertEqual(self.bridge.status["diagnostic_code"], "")
        self.assertNotIn("remote text", str(self.log_info.call_args_list))

    def test_match_slots_isolate_requests_and_publish_target_lease(self):
        bridges = [ipc.IdentityBridge(slot=i) for i in (0, 1)]
        try:
            for i, bridge in enumerate(bridges):
                root = bridge._root
                ipc._write_json(
                    root / "status.json",
                    dict(
                        state="idle",
                        target="",
                        transaction="",
                        message="",
                        accepts_begin=True,
                        updated_at=datetime.now(UTC).isoformat(),
                        steam_lifecycle=ipc._MATCH_LIFECYCLE,
                    ),
                )
                bridge.hold_target = str(76561198049468923 + i)
                bridge.expected_account = ACCOUNT
                bridge.set_requests_enabled(True)
                bridge.start()
                self.assertTrue(bridge.begin(bridge.hold_target))
                lease = ipc._read_json(root / "clients" / (bridge._client + ".json"))
                self.assertEqual(lease["hold_target"], bridge.hold_target)
                self.assertEqual(lease["expected_account"], ACCOUNT)
                request = ipc._read_json(root / "requests" / (bridge._pending + ".json"))
                self.assertEqual(request["expected_account"], ACCOUNT)
                self.assertEqual(len(list((root / "requests").glob("*.json"))), 1)
            bridges[0].stop()
            self.assertEqual(bridges[0].hold_target, "")
            self.assertTrue(list((self.root.parent / "match-0").glob("restore-*.json")))
            self.assertFalse(list((self.root.parent / "match-1").glob("restore-*.json")))
        finally:
            for bridge in bridges:
                bridge.stop()

    def test_match_worker_launch_uses_slot_and_rejects_legacy_capability(self):
        bridge = ipc.IdentityBridge(slot=1)
        bridge.expected_account = ACCOUNT
        bridge.set_requests_enabled(True)
        try:
            bridge.start()
            self.launch.assert_called_once_with(self.helper, 1)
            for lifecycle in (
                ipc._STEAM_LIFECYCLE,
                "match_hold_v1",
                "match_hold_v2",
                "match_hold_v3",
                "on_demand_v1",
            ):
                ipc._write_json(
                    bridge._root / "status.json",
                    dict(
                        state="idle",
                        target="",
                        transaction="",
                        message="",
                        accepts_begin=True,
                        updated_at=datetime.now(UTC).isoformat(),
                        steam_lifecycle=lifecycle,
                    ),
                )
                bridge._poll()
                self.assertFalse(bridge.begin("76561198049468923"))
                self.assertFalse((bridge._root / "clients" / (bridge._client + ".json")).exists())
        finally:
            bridge.stop()

    def test_start_launches_detached_recovery_when_status_stale(self):
        self.status(age=60)
        self.bridge.start()
        self.bridge._poll()
        self.launch.assert_called_once_with(self.helper, 0)
        self.assertEqual(self.bridge.status["state"], "preparing")
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())

    def test_fresh_legacy_idle_never_renews_lease_or_accepts_begin(self):
        self.status(lifecycle=None)
        with patch.object(ipc, "_write_json", wraps=ipc._write_json) as write:
            self.bridge.start()
            for _ in range(3):
                self.bridge._last_lease -= 10
                self.bridge._poll()
            self.assertFalse(self.bridge.begin("76561198049468923"))
            write.assert_not_called()
        self.assertFalse(self.bridge.status["accepts_begin"])
        self.assertIn("旧版", self.bridge.status["message"])
        self.launch.assert_not_called()

    def test_detecting_legacy_drops_only_this_clients_existing_lease(self):
        self.status()
        self.bridge.start()
        ours = self.root / "clients" / (self.bridge._client + ".json")
        foreign = self.root / "clients" / ("f" * 32 + ".json")
        ipc._write_json(foreign, {"client": "f" * 32})
        foreign_content, foreign_time = foreign.read_bytes(), foreign.stat().st_mtime_ns
        self.status(lifecycle=None)
        self.bridge._poll()
        self.assertFalse(ours.exists())
        self.assertEqual(foreign.read_bytes(), foreign_content)
        self.assertEqual(foreign.stat().st_mtime_ns, foreign_time)
        self.assertFalse(self.bridge.begin("76561198049468923"))
        self.launch.assert_not_called()

    def test_legacy_recovery_preserves_transaction_and_journal_without_lease(self):
        transaction = self.begin()
        journal = self.root / "journal-test.json"
        claim = self.root / "active-request.json"
        ipc._write_json(journal, {"transaction": transaction, "recovery_needed": True})
        ipc._write_json(claim, {"transaction": transaction})
        saved_journal, saved_claim = journal.read_bytes(), claim.read_bytes()
        self.status("blocked", transaction, lifecycle=None)
        self.bridge._poll()
        self.assertEqual(self.bridge._pending, transaction)
        self.assertEqual(self.bridge.status["state"], "recovery_pending")
        self.assertFalse(self.bridge.status["accepts_begin"])
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        self.bridge.restore()
        self.assertTrue((self.root / ("restore-" + transaction + ".json")).is_file())
        self.assertEqual(journal.read_bytes(), saved_journal)
        self.assertEqual(claim.read_bytes(), saved_claim)
        self.assertFalse(self.bridge.begin("76561198049468924"))
        self.launch.assert_not_called()

    def test_legacy_idle_cannot_discard_a_missing_pending_request(self):
        transaction = self.begin()
        (self.root / "requests" / (transaction + ".json")).unlink()
        self.bridge._pending_since = time.monotonic() - 31
        self.status(lifecycle=None)
        self.bridge._poll()
        self.assertEqual(self.bridge._pending, transaction)
        self.assertEqual(self.bridge.status["state"], "recovery_pending")
        self.assertFalse(self.bridge.status["accepts_begin"])

    def test_matching_legacy_restore_is_consumed_but_cannot_authorize_new_begin(self):
        transaction = self.begin()
        self.status("restored", transaction, lifecycle=None, accepts_begin=True)
        self.bridge._poll()
        self.assertIsNone(self.bridge._pending)
        self.assertEqual(self.bridge.status["state"], "restored")
        self.assertFalse(self.bridge.status["accepts_begin"])
        self.assertFalse(self.bridge.begin("76561198049468924"))

    def test_result_file_finishes_legacy_request_without_claiming_worker_compatibility(self):
        transaction = self.begin()
        ipc._write_json(
            self.root / "results" / (transaction + ".json"),
            {
                "state": "restored",
                "transaction": transaction,
                "target": "76561198049468923",
                "accepts_begin": True,
                "message": "done",
            },
        )
        self.status(lifecycle=None)
        self.bridge._poll()
        self.assertIsNone(self.bridge._pending)
        self.assertTrue(
            any(
                x["transaction"] == transaction and x["state"] == "restored" and not x["accepts_begin"]
                for x in self.events
            )
        )
        self.assertFalse(self.bridge.begin("76561198049468924"))

    def test_stale_legacy_launch_races_never_renew_lease_until_new_worker_is_observed(self):
        self.status(age=60, lifecycle=None)
        self.bridge.start()
        self.assertEqual(self.launch.call_count, 1)
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        self.bridge._last_launch -= 6
        self.bridge._poll()
        self.assertEqual(self.launch.call_count, 2)
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        # The old singleton owner briefly starts heartbeating again.
        self.status(lifecycle=None)
        self.bridge._poll()
        self.assertEqual(self.launch.call_count, 2)
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        # A successful new owner is the first point at which a lease is written.
        self.status()
        self.bridge._poll()
        self.assertTrue((self.root / "clients" / (self.bridge._client + ".json")).exists())
        self.assertTrue(self.bridge.begin("76561198049468923"))

    def test_missing_status_starts_worker_without_assuming_singleton_was_acquired(self):
        self.bridge.start()
        self.launch.assert_called_once_with(self.helper, 0)
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        self.assertFalse(self.bridge.begin("76561198049468923"))
        self.status()
        self.bridge._poll()
        self.assertTrue(self.bridge.begin("76561198049468923"))

    def test_stale_compatible_status_also_removes_existing_lease(self):
        self.status()
        self.bridge.start()
        self.status(age=30)
        self.bridge._poll()
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        self.assertFalse(self.bridge.status["accepts_begin"])
        self.assertFalse(self.bridge.begin("76561198049468923"))

    def test_blocked_worker_missing_heartbeat_keeps_verified_lease_for_thirty_seconds(self):
        transaction = self.begin()
        self.bridge.authorize_hold("76561198049468923")
        self.status("blocked", transaction)
        self.bridge._poll()
        lease = self.root / "clients" / (self.bridge._client + ".json")
        for missing in (False, True):
            if missing:
                (self.bridge._root / "status.json").unlink()
            else:
                self.status("blocked", transaction, age=12)
            self.bridge._last_lease -= 2
            self.bridge._poll()
            self.assertEqual(ipc._read_json(lease)["hold_target"], "76561198049468923")
            self.assertEqual(self.bridge.status["state"], "blocked")
            self.assertFalse(self.bridge.status["accepts_begin"])
            self.assertEqual(self.bridge._poll_reason, "worker_outage_grace")
            self.launch.assert_not_called()
        self.bridge._last_compatible_seen -= 31
        self.bridge._poll()
        self.assertFalse(lease.exists())
        self.launch.assert_called_once_with(self.helper, 0)

    def test_fresh_old_worker_revokes_grace_without_touching_its_journal(self):
        transaction = self.begin()
        self.status("blocked", transaction)
        self.bridge._poll()
        self.status("blocked", transaction, lifecycle="on_demand_v1")
        self.bridge._poll()
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        self.assertEqual(self.bridge._poll_reason, "old_lifecycle")
        self.assertFalse(self.bridge.begin("76561198049468924"))

    def test_completed_worker_exit_consumes_result_then_starts_clean_idle_process(self):
        transaction = self.begin()
        self.status("restored", transaction, worker_exiting=True)
        ipc._write_json(
            self.root / "results" / f"{transaction}.json",
            dict(state="restored", target="76561198049468923", transaction=transaction, message="restored"),
        )
        self.bridge._poll()
        self.assertFalse(self.bridge.pending)
        self.assertTrue(any(e["state"] == "restored" for e in self.events))
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        self.launch.assert_called_once_with(self.helper, 0)
        self.assertFalse(self.bridge.status["accepts_begin"])
        self.status()
        self.bridge._poll()
        self.assertTrue(self.bridge.begin("76561198049468924"))

    def test_unknown_lifecycle_marker_is_not_accepted(self):
        self.status(lifecycle="different-contract")
        self.bridge.start()
        self.assertFalse(self.bridge.begin("76561198049468923"))
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())

    def test_failed_lease_write_cannot_enable_requests(self):
        self.status()
        with patch.object(ipc, "_write_json", side_effect=OSError("read only")):
            self.bridge.start()
            self.assertFalse(self.bridge.begin("76561198049468923"))
        self.assertFalse(self.bridge.status["accepts_begin"])
        self.assertEqual(self.bridge.status["state"], "recovery_pending")
        self.assertFalse((self.root / "requests").exists())

    def test_begin_exposes_transaction_synchronously_and_rejects_parallel(self):
        transaction = self.begin()
        self.assertEqual(len(transaction), 32)
        request = ipc._read_json(self.root / "requests" / (transaction + ".json"))
        self.assertEqual(request["transaction"], transaction)
        self.assertEqual(request["client"], self.bridge._client)
        self.assertEqual(self.events[-1]["state"], "preparing")
        self.assertFalse(self.bridge.begin("76561198049468924"))

    def test_begin_poll_callback_cannot_overwrite_another_pending_transaction(self):
        self.status()
        self.bridge.start()
        accepted = []

        def begin_on_ready(value):
            if value["state"] == "restored" and value["accepts_begin"]:
                accepted.append(self.bridge.begin("76561198049468924"))

        self.bridge.changed.connect(begin_on_ready)
        self.status("restored")
        self.assertFalse(self.bridge.begin("76561198049468923"))
        self.assertEqual(accepted, [True])
        requests = list((self.root / "requests").glob("*.json"))
        self.assertEqual(len(requests), 1)
        self.assertEqual(ipc._read_json(requests[0])["target"], "76561198049468924")
        self.assertEqual(self.bridge._pending, requests[0].stem)

    def test_invalid_identifiers_never_reach_worker(self):
        self.status()
        self.bridge.start()
        for value in ["../account", "0", "76561198049468923x", "９" * 17, "99999999999999999"]:
            self.assertFalse(self.bridge.begin(value))
        self.assertFalse((self.root / "requests").exists())

    def test_stop_requests_restore_and_removes_lease_without_killing_worker(self):
        transaction = self.begin()
        worker = Mock()
        self.bridge._worker = worker
        self.bridge.stop()
        self.assertTrue((self.root / ("restore-" + transaction + ".json")).is_file())
        self.assertFalse((self.root / "clients" / (self.bridge._client + ".json")).exists())
        worker.terminate.assert_not_called()
        worker.kill.assert_not_called()

    def test_matching_terminal_status_recovers_when_result_file_was_lost(self):
        transaction = self.begin()
        self.status("restored", transaction)
        self.bridge._poll()
        self.assertIsNone(self.bridge._pending)
        self.assertEqual(self.bridge.status["state"], "restored")
        self.assertTrue(self.bridge.begin("76561198049468924"))

    def test_restore_is_noop_for_completed_or_rejected_transaction(self):
        for terminal in ("restored", "error", "idle"):
            with self.subTest(terminal=terminal):
                self.status()
                self.bridge.start()
                self.assertTrue(self.bridge.begin("76561198049468923"))
                transaction = self.bridge._pending
                ipc._write_json(
                    self.root / "results" / f"{transaction}.json",
                    dict(
                        state="error" if terminal == "error" else "restored",
                        target="76561198049468923",
                        transaction=transaction,
                        message="done",
                    ),
                )
                self.status(terminal, transaction)
                self.bridge._poll()
                self.assertFalse(self.bridge.pending)
                self.bridge.hold_target = "76561198049468923"
                self.bridge.restore()
                self.assertEqual(self.bridge.hold_target, "")
                self.assertEqual(self.bridge.status["state"], terminal)
                self.assertFalse((self.root / f"restore-{transaction}.json").exists())

    def test_unrelated_terminal_status_does_not_clear_active_request(self):
        transaction = self.begin()
        self.status("restored", "a" * 32)
        self.bridge._poll()
        self.assertEqual(self.bridge._pending, transaction)
        self.assertEqual(self.bridge.status["state"], "preparing")

    def test_result_file_finishes_request_after_worker_status_moved_on(self):
        transaction = self.begin()
        ipc._write_json(
            self.root / "results" / (transaction + ".json"),
            {
                "state": "restored",
                "transaction": transaction,
                "target": "76561198049468923",
                "message": "done",
            },
        )
        self.status()
        self.bridge._poll()
        self.assertIsNone(self.bridge._pending)
        self.assertTrue(
            any(x["state"] == "restored" and x["transaction"] == transaction for x in self.events)
        )

    def test_lost_request_can_retry_only_after_fresh_idle_without_pending_journal(self):
        transaction = self.begin()
        (self.root / "requests" / (transaction + ".json")).unlink()
        self.bridge._pending_since = time.monotonic() - 31
        self.status()
        ipc._write_json(self.root / "active-request.json", {"transaction": transaction})
        self.bridge._poll()
        self.assertEqual(self.bridge._pending, transaction)
        (self.root / "active-request.json").unlink()
        journal_path = self.root / "journal-test.json"
        journal_path.write_text("broken", encoding="utf-8")
        self.bridge._poll()
        self.assertEqual(self.bridge._pending, transaction)
        ipc._write_json(journal_path, {"transaction": transaction, "recovery_needed": True})
        self.bridge._poll()
        self.assertEqual(self.bridge._pending, transaction)
        ipc._write_json(journal_path, {"transaction": transaction, "recovery_needed": False})
        self.bridge._poll()
        self.assertIsNone(self.bridge._pending)
        self.assertEqual(self.bridge.status["state"], "error")

    def test_worker_restart_retains_pending_transaction(self):
        transaction = self.begin()
        self.status("blocked", transaction, age=30)
        self.bridge._last_compatible_seen -= 31
        self.bridge._poll()
        self.launch.assert_called_once()
        self.assertEqual(self.bridge._pending, transaction)
        self.assertEqual(self.bridge.status["state"], "recovery_pending")

    def test_transport_does_not_expose_extra_worker_fields(self):
        self.status(account="private actor", session="never forward")
        self.bridge.start()
        self.assertNotIn("account", self.bridge.status)
        self.assertNotIn("session", self.events[-1])

    def test_diagnostics_log_capability_changes_without_private_values_or_poll_spam(self):
        private = "remote-private-76561198049468923-session-secret"
        self.status(account=private, message=private, session=private, transaction="f" * 32)
        self.bridge.start()
        first_count = self.log_info.call_count
        for index in range(5):
            # Native heartbeat, message, and identity changes are not diagnostic
            # transitions and must not turn the 200 ms poll into an INFO stream.
            self.status(
                account=private,
                message=private + str(index),
                target=private,
                session=private,
                transaction="f" * 32,
            )
            self.bridge._poll()
        self.assertEqual(self.log_info.call_count, first_count)
        self.status(accepts_begin=False, message=private)
        self.bridge._poll()
        self.assertEqual(self.log_info.call_count, first_count + 1)
        self.status(lifecycle=private, message=private)
        self.bridge._poll()
        self.assertEqual(self.log_info.call_count, first_count + 2)
        logs = "\n".join(
            str(call.args[0]) for call in self.log_info.call_args_list + self.log_warning.call_args_list
        )
        for secret in (private, "76561198049468923", "f" * 32):
            self.assertNotIn(secret, logs)
        self.assertIn("compatible=False", logs)
        self.assertIn("accepts_begin=False", logs)
        self.assertIn("pending=False", logs)

    def test_early_child_exit_is_logged_once_and_identical_retries_are_throttled(self):
        self.process.poll.return_value = 7
        with patch.object(ipc.time, "monotonic", return_value=100.0) as now:
            self.bridge.start()
            for _ in range(5):
                self.bridge._poll()
            self.log_warning.assert_called_once()
            self.assertIn("exitcode=7", self.log_warning.call_args.args[0])
            self.assertIn(str(self.helper), self.log_warning.call_args.args[0])
            self.assertIn(str(self.helper), self.log_info.call_args_list[0].args[0])
            now.return_value = 106.0
            self.bridge._poll()  # A new launch is still allowed after five seconds.
            self.bridge._poll()  # Repeated identical exit remains quiet.
            self.assertEqual(self.launch.call_count, 2)
            self.assertEqual(self.log_warning.call_count, 1)
            now.return_value = 132.0
            self.bridge._poll()
            self.bridge._poll()
            self.assertEqual(self.log_warning.call_count, 2)
        self.process.stderr.read.assert_not_called()
        self.process.terminate.assert_not_called()
        self.process.kill.assert_not_called()

    def test_launch_failure_logs_path_without_exception_contents(self):
        private = "remote-private-76561198049468923-session-secret"
        self.launch.side_effect = OSError(private)
        with patch.object(ipc.time, "monotonic", return_value=100.0) as now:
            self.bridge.start()
            now.return_value = 106.0
            self.bridge._poll()
        self.assertEqual(self.launch.call_count, 2)
        self.log_warning.assert_called_once()
        logs = "\n".join(
            str(call.args[0]) for call in self.log_info.call_args_list + self.log_warning.call_args_list
        )
        self.assertIn(str(self.helper), logs)
        self.assertIn("launch failed", logs)
        self.assertNotIn(private, logs)


if __name__ == "__main__":
    unittest.main()
