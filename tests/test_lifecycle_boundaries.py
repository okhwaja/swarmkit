"""Pause, drain, and cancellation cover every owned kind of work."""

from pathlib import Path
import tempfile
import unittest

import swarmctl as s
from swarmkit import coordination, delivery


class LifecycleBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-lifecycle-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Handle work", ["Verified"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def review(self):
        review_id, _ = s.request_manager_review(
            self.conn, "Plan", "mission", s.mission(self.conn)["id"]
        )
        s.claim_manager_review(self.conn, "manager", 60)
        return review_id

    def pending_delivery(self):
        source = Path(s.__file__).parent / "examples/extensions/harness-email"
        s.install_extension(self.conn, source, "human")
        content = self.root.parent / "report.md"
        content.write_text("Progress")
        return s.enqueue_delivery(
            self.root,
            self.conn,
            "harness-email-example",
            "email",
            "Progress",
            ["replace-me@example.com"],
            content,
            [],
            "report-1",
            "human",
        )["id"]

    def test_pause_fences_manager_commit_and_late_completion(self):
        review = self.review()
        s.control_mission(self.conn, "pause", "human", "Change plans")
        with self.assertRaises(s.SwarmError):
            coordination.commit_review(
                self.conn,
                review,
                "manager",
                [{"disposition": "no-change", "rationale": "Checked"}],
                "Checked",
            )
        coordination.finish_manager_review(self.conn, review, "manager", True)
        row = self.conn.execute("SELECT * FROM manager_reviews WHERE id=?", (review,)).fetchone()
        self.assertEqual(row["status"], "PENDING")
        self.assertIsNone(row["owner"])

    def test_cancel_withdraws_pending_manager_work(self):
        review = self.review()
        s.control_mission(self.conn, "cancel", "human", "Withdrawn")
        coordination.finish_manager_review(self.conn, review, "manager", True)
        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM manager_reviews WHERE id=?", (review,)
            ).fetchone()[0],
            "CANCELLED",
        )

    def test_drain_waits_for_claimed_delivery_then_pauses(self):
        job = self.pending_delivery()
        delivery.claim_delivery(self.conn, job, "sender", 60)
        state = s.control_mission(self.conn, "drain", "human", "Finish sending")
        self.assertEqual(state["desired_state"], "DRAINING")
        delivery.mark_delivery_sent(self.conn, job, "sender", "provider-receipt")
        s.reconcile_conn(self.conn)
        self.assertEqual(s.runtime_state(self.conn)["desired_state"], "PAUSED")

    def test_drain_and_resume_wait_for_sender_process_after_receipt(self):
        job = self.pending_delivery()
        delivery.claim_delivery(self.conn, job, "sender", 60)
        self.conn.execute(
            """INSERT INTO delivery_runs(id,mission_id,delivery_id,extension_id,executor_type,
               agent_id,envelope_path,command_json,started_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                "DR-fixture",
                s.mission(self.conn)["id"],
                job,
                "harness-email-example",
                "command",
                "sender",
                "envelope.json",
                "[]",
                s.utcnow(),
            ),
        )
        self.conn.commit()
        delivery.mark_delivery_sent(self.conn, job, "sender", "provider-receipt")
        self.assertEqual(
            s.control_mission(self.conn, "drain", "human", "Finish sender")["desired_state"],
            "DRAINING",
        )
        s.reconcile_conn(self.conn)
        self.assertEqual(s.runtime_state(self.conn)["desired_state"], "DRAINING")
        with self.assertRaises(s.SwarmError):
            s.control_mission(self.conn, "resume", "human", "Continue")
        self.conn.execute(
            "UPDATE delivery_runs SET ended_at=? WHERE id='DR-fixture'", (s.utcnow(),)
        )
        self.conn.commit()
        s.reconcile_conn(self.conn)
        self.assertEqual(s.runtime_state(self.conn)["desired_state"], "PAUSED")
        s.control_mission(self.conn, "resume", "human", "Continue")

    def test_cancel_cannot_hide_delivery_uncertainty_or_inflight_send(self):
        job = self.pending_delivery()
        delivery.claim_delivery(self.conn, job, "sender", 60)
        with self.assertRaises(s.SwarmError):
            delivery.cancel_delivery(self.conn, job, "human", "Stop")
        self.conn.execute(
            "UPDATE deliveries SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (job,)
        )
        self.conn.commit()
        s.reconcile_deliveries(self.conn)
        with self.assertRaises(s.SwarmError):
            delivery.cancel_delivery(self.conn, job, "human", "Stop")
        s.control_mission(self.conn, "pause", "human", "Investigate")
        with self.assertRaises(s.SwarmError):
            s.control_mission(self.conn, "resume", "human", "Continue")

    def test_drain_waits_for_manager_review_without_registered_harness(self):
        review = self.review()
        self.assertEqual(
            s.control_mission(self.conn, "drain", "human", "Finish planning")["desired_state"],
            "DRAINING",
        )
        coordination.commit_review(
            self.conn,
            review,
            "manager",
            [{"disposition": "no-change", "rationale": "Checked"}],
            "Checked",
        )
        coordination.finish_manager_review(self.conn, review, "manager", True)
        s.reconcile_conn(self.conn)
        self.assertEqual(s.runtime_state(self.conn)["desired_state"], "PAUSED")
