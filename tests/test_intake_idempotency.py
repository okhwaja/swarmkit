"""Retries identify durable operations by keys, never by human-readable prose."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import policies, schema


class IntakeIdempotencyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-intake-keys-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Review changes", ["Verified"], [], "SERVICE")
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)
        self.policy_id = "performance-investigation"
        s.install_policy(
            self.conn, Path(s.__file__).parent / "examples/policy-packs" / self.policy_id, "human"
        )

    def apply(self, **changes):
        args = dict(
            policy_id=self.policy_id,
            variable_items=["goal=Reduce latency", "test_command=tests"],
            workstream_id=None,
            actor="manager",
            ready=True,
            idempotency_key="review-1",
        )
        args.update(changes)
        return policies.apply_policy(self.conn, **args)

    def case(self):
        return s.open_case(
            self.root,
            self.conn,
            "review",
            "change-1",
            "Review",
            "Inspect",
            50,
            "ingress",
            [],
            ready=True,
        )

    def signal(self, case, wake=True):
        return s.add_case_signal(
            self.root,
            self.conn,
            case["id"],
            "review",
            "event-1",
            "reply",
            None,
            "Updated",
            "ingress",
            wake=wake,
        )

    def test_existing_case_retry_after_mission_cancel_returns_original(self):
        case = self.case()
        s.control_mission(self.conn, "cancel", "human", "Withdrawn")
        again = self.case()
        self.assertEqual(again["id"], case["id"])
        self.assertFalse(again["created"])
        self.assertEqual(again["status"], "CANCELLED")

    def test_identical_policy_retry_returns_same_plan_even_when_paused(self):
        first = self.apply()
        before = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        s.control_mission(self.conn, "pause", "human", "Wait")
        paused = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        again = self.apply(
            actor="replacement-manager",
            variable_items=["test_command=tests", "goal=Reduce latency"],
        )
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(first["tasks"], again["tasks"])
        self.assertGreater(paused, before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], paused)

    def test_key_cannot_be_reused_for_changed_work_or_policy_guidance(self):
        self.apply()
        with self.assertRaises(s.SwarmError):
            self.apply(ready=False)
        self.conn.execute("UPDATE policy_packs SET guidance_text=guidance_text || ' changed'")
        self.conn.commit()
        with self.assertRaises(s.SwarmError):
            self.apply()

    def test_policy_failure_does_not_consume_key(self):
        with mock.patch.object(policies, "add_event", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.apply()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM policy_application_keys").fetchone()[0], 0
        )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        self.apply()

    def test_signal_retry_survives_task_description_edit_and_case_cancellation(self):
        case = self.case()
        signal = self.signal(case)
        self.conn.execute(
            "UPDATE tasks SET description='Clarified follow-up scope' WHERE id=?",
            (signal["wake_task_id"],),
        )
        self.conn.commit()
        repeated = self.signal(case)
        self.assertEqual(repeated["wake_task_id"], signal["wake_task_id"])
        s.cancel_case(self.conn, case["id"], "human", "Withdrawn")
        self.assertEqual(self.signal(case)["wake_task_id"], signal["wake_task_id"])

    def test_task_mentioning_signal_does_not_suppress_real_followup(self):
        case = self.case()
        signal = self.signal(case, wake=False)
        initial = case["tasks"][0]["id"]
        self.conn.execute(
            "UPDATE tasks SET description=? WHERE id=?",
            ("Background mentions signal " + signal["id"], initial),
        )
        self.conn.commit()
        self.assertNotEqual(self.signal(case)["wake_task_id"], initial)

    def test_migration_recovers_signal_identity_from_event_not_description(self):
        case = self.case()
        signal = self.signal(case)
        self.conn.execute("DELETE FROM case_signal_tasks")
        self.conn.execute(
            "UPDATE tasks SET description='Clarified scope' WHERE id=?", (signal["wake_task_id"],)
        )
        schema.migrate_reliability_schema(self.conn)
        self.conn.commit()
        self.assertEqual(self.signal(case)["wake_task_id"], signal["wake_task_id"])
