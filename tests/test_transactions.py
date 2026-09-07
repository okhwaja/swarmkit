"""A command either records its entire durable result or records none of it."""

import contextlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from swarmkit import coordination, runtime, schema, workspaces

import swarmctl as s


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-transactions-")
        self.root = Path(self.temp.name).resolve() / ".swarm"
        s.initialize(self.root, "Atomic work", ["Verified"], [], "SERVICE")
        self.conn = s.connect(self.root)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def task(self):
        return s.add_task(
            self.conn,
            "Investigate",
            "Investigate",
            "discovery",
            ["Checked"],
            [],
            50,
            "manager",
            True,
        )

    def case(self, **kwargs):
        return s.open_case(
            self.root,
            self.conn,
            "provider",
            "request-1",
            "Inspect change",
            "Review safely",
            50,
            "ingress",
            ["Checked"],
            ready=True,
            **kwargs
        )

    def count(self, table):
        return self.conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_outer_transaction_can_rollback_a_complete_task_plan(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self.task()
        self.task()
        self.conn.rollback()
        self.assertEqual(self.count("tasks"), 0)

    def test_case_with_invalid_policy_leaves_no_partial_case_or_workstream(self):
        with self.assertRaises(s.SwarmError):
            self.case(policy_id="missing-policy")
        self.assertEqual(self.count("cases"), 0)
        self.assertEqual(self.count("workstreams"), 0)
        self.assertEqual(self.count("case_tasks"), 0)

    def test_case_task_quota_failure_is_retryable_after_limit_increase(self):
        s.configure_runtime(self.conn, {"max_tasks": 1})
        self.task()
        with self.assertRaises(s.SwarmError):
            self.case()
        self.assertEqual(self.count("cases"), 0)
        s.configure_runtime(self.conn, {"max_tasks": 2})
        result = self.case()
        self.assertTrue(result["created"])
        self.assertEqual(self.count("case_tasks"), 1)

    def test_signal_and_wakeup_are_one_transaction(self):
        case = self.case()
        s.configure_runtime(self.conn, {"max_tasks": 1})
        with self.assertRaises(s.SwarmError):
            s.add_case_signal(
                self.root,
                self.conn,
                case["id"],
                "provider",
                "event-1",
                "reply",
                None,
                "Please review",
                "ingress",
                wake=True,
            )
        self.assertEqual(self.count("case_signals"), 0)
        self.assertEqual(self.count("tasks"), 1)

    def test_late_event_failure_rolls_back_task_and_reconciliation(self):
        before = self.count("events")
        real_add_event = s.add_event

        def add_event(*args, **kwargs):
            if len(args) > 4 and args[4] == "TASK_READY":
                raise RuntimeError("injected write failure")
            return real_add_event(*args, **kwargs)

        with mock.patch.object(coordination, "add_event", side_effect=add_event):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.task()
        self.assertEqual(self.count("tasks"), 0)
        self.assertEqual(self.count("events"), before)

    def test_commit_failure_rolls_back_instead_of_leaving_pending_writes(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with s.transaction(self.conn):
                self.conn.execute("PRAGMA defer_foreign_keys=ON")
                self.conn.execute(
                    "INSERT INTO task_dependencies(task_id,depends_on) VALUES('missing-task','missing-dependency')")
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.count("task_dependencies"), 0)

    def test_nested_failure_can_be_caught_without_losing_the_outer_plan(self):
        with s.transaction(self.conn):
            task = self.task()
            with self.assertRaises(s.SwarmError):
                self.case(policy_id="missing-policy")
            self.assertEqual(s.task_row(self.conn, task)["status"], "READY")
        self.assertEqual(self.count("tasks"), 1)
        self.assertEqual(self.count("cases"), 0)

    def test_checkpoint_rejects_nonpositive_lease_without_changing_state(self):
        task = self.task()
        s.claim_task(self.conn, task, "worker", 600)
        before = dict(s.task_row(self.conn, task))
        with self.assertRaises(s.SwarmError):
            s.checkpoint_task(self.conn, task, "worker", "Keep working", "Inspect", 0)
        self.assertEqual(dict(s.task_row(self.conn, task)), before)

    def test_all_lease_timestamps_use_the_same_sortable_format(self):
        task = self.task()
        s.claim_task(self.conn, task, "worker", 600)
        lease = s.acquire_resource(self.conn, "benchmark-host", task, "worker", 30)
        self.assertRegex(lease["lease_until"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_cancelled_case_cannot_be_resurrected_by_linking_a_task(self):
        case = self.case()
        s.cancel_case(self.conn, case["id"], "human", "Stop this request")
        task = self.task()
        with self.assertRaises(s.SwarmError):
            s.link_case_task(self.conn, case["id"], task, "manager")
        self.assertEqual(s.case_row(self.conn, case["id"])["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
