"""A missing delivery receipt is uncertainty, never permission to send twice."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import delivery


class DeliveryRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-delivery-")
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / ".swarm"
        s.initialize(self.root, "Report progress", ["Receipt recorded"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def enqueue(self, code, timeout=5):
        folder = self.base / "extension"
        folder.mkdir()
        manifest = {
            "schema_version": 1,
            "id": "test-delivery",
            "version": "1",
            "name": "Test",
            "kind": "delivery",
            "description": "Local test adapter",
            "handles": ["email"],
            "guidance": "GUIDANCE.md",
            "executor": {
                "type": "command",
                "command": [sys.executable, "-c", code, "{envelope_file}"],
                "timeout_seconds": timeout,
            },
            "recipient_policy": {"allowed_recipients": ["test@example.com"], "allowed_domains": []},
        }
        (folder / "extension.json").write_text(json.dumps(manifest))
        (folder / "GUIDANCE.md").write_text(
            "Record a provider receipt before calling delivery sent."
        )
        content = self.base / "message.txt"
        content.write_text("Test content")
        s.install_extension(self.conn, folder, "test")
        return s.enqueue_delivery(
            self.root,
            self.conn,
            "test-delivery",
            "email",
            "Status",
            ["test@example.com"],
            content,
            [],
            "test-1",
            "test",
        )["id"]

    def test_clean_exit_without_receipt_is_not_replayable(self):
        item = self.enqueue("print('provider may already have accepted the message')")
        result = s.dispatch_delivery(self.root, item, "adapter")
        self.assertEqual(result["delivery_status"], "UNKNOWN")
        with self.assertRaises(s.SwarmError):
            s.claim_delivery(self.conn, item, "another-adapter")
        with self.assertRaises(s.SwarmError):
            s.retry_delivery(self.conn, item, "operator")

    def test_supervision_error_cannot_hide_live_sender_from_recovery(self):
        item = self.enqueue("import time; time.sleep(30)")
        children = []

        def lose_supervision(command, workdir, timeout, stdout, stderr, lock):
            children.append(
                subprocess.Popen(
                    command,
                    cwd=workdir,
                    pass_fds=(lock.fileno(),),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            raise OSError("Could not verify sender cleanup")

        try:
            with mock.patch.object(delivery, "run_logged_process", side_effect=lose_supervision):
                with self.assertRaises(OSError):
                    s.dispatch_delivery(self.root, item, "adapter")
            run = self.conn.execute("SELECT * FROM delivery_runs").fetchone()
            self.assertIsNone(run["ended_at"])
            self.assertIsNotNone(run["stdout_path"])
            self.assertTrue(s.recover_runs(self.root)["live_or_unverified"])
            self.conn.execute(
                "UPDATE deliveries SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (item,)
            )
            self.conn.commit()
            s.reconcile_conn(self.conn)
            with self.assertRaises(s.SwarmError):
                delivery.reconcile_delivery(self.conn, item, "not-sent", "Observation", "operator")
            children[0].kill()
            children[0].wait(timeout=5)
            self.assertEqual(s.recover_runs(self.root)["recovered"], [run["id"]])
            self.assertEqual(
                self.conn.execute("SELECT status FROM deliveries WHERE id=?", (item,)).fetchone()[
                    0
                ],
                "UNKNOWN",
            )
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)

    def test_expired_claim_requires_provider_reconciliation(self):
        item = self.enqueue("pass")
        s.claim_delivery(self.conn, item, "adapter")
        self.conn.execute(
            "UPDATE deliveries SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (item,)
        )
        self.conn.commit()
        s.reconcile_conn(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT status FROM deliveries WHERE id=?", (item,)).fetchone()[0],
            "UNKNOWN",
        )

    def test_timeout_with_partial_output_closes_run_and_keeps_uncertainty(self):
        item = self.enqueue(
            "import sys,time; print('partial output',flush=True); time.sleep(10)", timeout=1
        )
        result = s.dispatch_delivery(self.root, item, "adapter")
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["delivery_status"], "UNKNOWN")
        self.assertIn("partial output", Path(result["stdout"]).read_text())
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM delivery_runs WHERE ended_at IS NULL"
            ).fetchone()[0],
            0,
        )

    def test_provider_receipt_can_resolve_uncertainty_without_resending(self):
        item = self.enqueue("pass")
        s.dispatch_delivery(self.root, item, "adapter")
        resolved = delivery.reconcile_delivery(
            self.conn, item, "sent", "provider-message-1", "operator"
        )
        self.assertEqual(resolved["status"], "SENT")
        self.assertEqual(resolved["attempt_count"], 1)
        with self.assertRaises(s.SwarmError):
            s.claim_delivery(self.conn, item, "another-adapter")

    def test_provider_proof_of_non_delivery_allows_a_deliberate_retry(self):
        item = self.enqueue("pass")
        s.dispatch_delivery(self.root, item, "adapter")
        resolved = delivery.reconcile_delivery(
            self.conn, item, "not-sent", "provider lookup found no accepted request", "operator"
        )
        self.assertEqual(resolved["status"], "PENDING")
        s.claim_delivery(self.conn, item, "another-adapter")
        s.mark_delivery_sent(self.conn, item, "another-adapter", "provider-message-2")

    def test_upgrade_reclassifies_legacy_ambiguous_delivery(self):
        item = self.enqueue("pass")
        self.conn.execute(
            "UPDATE deliveries SET status='PENDING',attempt_count=1,last_error='Delivery lease expired before provider acknowledgment' WHERE id=?",
            (item,),
        )
        self.conn.execute("UPDATE meta SET value='8' WHERE key='schema_version'")
        self.conn.commit()
        upgraded = s.connect(self.root)
        try:
            self.assertEqual(
                upgraded.execute("SELECT status FROM deliveries WHERE id=?", (item,)).fetchone()[0],
                "UNKNOWN",
            )
            self.assertEqual(
                upgraded.execute(
                    "SELECT COUNT(*) FROM events WHERE entity_id=? AND event_type='DELIVERY_MIGRATED_TO_UNKNOWN'",
                    (item,),
                ).fetchone()[0],
                1,
            )
        finally:
            upgraded.close()

    def test_final_report_can_be_delivered_after_mission_completion(self):
        item = self.enqueue("pass")
        s.complete_mission(self.conn, "The requested report is ready", "manager")
        s.claim_delivery(self.conn, item, "reporter")
        s.mark_delivery_sent(self.conn, item, "reporter", "final-report-receipt")

    def test_controller_crash_retains_child_lock_until_real_process_exit(self):
        pidfile = self.base / "child.pid"
        code = (
            "import os,time; from pathlib import Path; Path(%r).write_text(str(os.getpid())); time.sleep(30)"
            % str(pidfile)
        )
        item = self.enqueue(code, timeout=40)
        controller = subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(Path(s.__file__)),
                "--root",
                str(self.root),
                "delivery",
                "dispatch",
                item,
                "--agent",
                "adapter",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        child_pid = None
        try:
            deadline = time.monotonic() + 5
            while (
                not pidfile.exists() and controller.poll() is None and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            self.assertTrue(pidfile.exists(), "Adapter did not start")
            child_pid = int(pidfile.read_text())
            controller.kill()
            controller.wait(timeout=5)
            live = s.recover_runs(self.root)
            self.assertTrue(live["live_or_unverified"])
            os.killpg(child_pid, signal.SIGKILL)
            child_pid = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                recovered = s.recover_runs(self.root)
                if recovered["recovered"]:
                    break
                time.sleep(0.02)
            self.assertTrue(recovered["recovered"])
            self.assertEqual(
                self.conn.execute("SELECT status FROM deliveries WHERE id=?", (item,)).fetchone()[
                    0
                ],
                "UNKNOWN",
            )
        finally:
            if controller.poll() is None:
                controller.kill()
            controller.wait(timeout=5)
            controller.stderr.close()
            if child_pid:
                # Older dispatchers may not own a process group yet.
                try:
                    os.killpg(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
