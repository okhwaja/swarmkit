"""Inbox pages are bounded, ordered, and independently acknowledged per scope."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import inbox as delivery


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-inbox-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Read durable changes", ["No lost events"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def task(self, title="Inspect", depends_on=None):
        return s.add_task(
            self.conn, title, title, "discovery", ["Checked"], depends_on or [], 50, "manager", True
        )

    def test_lease_only_decodes_the_requested_page(self):
        task = self.task()
        with s.transaction(self.conn):
            for index in range(5000):
                s.add_event(
                    self.conn,
                    s.mission(self.conn)["id"],
                    "task",
                    task,
                    "TASK_CHECKPOINTED",
                    "worker",
                    {"index": index},
                )
        with mock.patch.object(delivery, "json_load", wraps=delivery.json_load) as decode:
            page = s.lease_inbox(self.conn, "reader", limit=7)
        self.assertEqual(len(page["events"]), 7)
        self.assertLessEqual(decode.call_count, 8)

    def test_pagination_has_no_duplicates_or_gaps(self):
        self.task()
        expected = [row[0] for row in self.conn.execute("SELECT seq FROM events ORDER BY seq")]
        actual = []
        while True:
            page = s.lease_inbox(self.conn, "reader", limit=2)
            if not page["events"]:
                break
            replay = s.lease_inbox(self.conn, "reader", limit=5)
            self.assertEqual(replay, page)
            actual.extend(event["seq"] for event in page["events"])
            s.ack_inbox(self.conn, page["token"], "reader")
        self.assertEqual(actual, expected)

    def test_legacy_advance_does_not_consume_another_task_scope(self):
        first = self.task("First")
        second = self.task("Second")
        s.inbox(self.conn, "reader", task_id=second, advance=True)
        events = s.inbox(self.conn, "reader", task_id=first)
        self.assertTrue(any(event["entity_id"] == first for event in events))

    def test_scoped_events_include_dependencies_but_exclude_unrelated_work(self):
        dependency = self.task("Upstream")
        task = self.task("Downstream", [dependency])
        unrelated = self.task("Other")
        with s.transaction(self.conn):
            artifact = s.register_artifact(self.conn, dependency, "https://example.test/result")
        events = s.inbox(self.conn, "reader", task_id=task)
        entities = {event["entity_id"] for event in events}
        self.assertIn(dependency, entities)
        self.assertIn(artifact, entities)
        self.assertNotIn(unrelated, entities)

    def test_legacy_advance_respects_outer_transaction(self):
        self.task()
        self.conn.execute("BEGIN IMMEDIATE")
        s.inbox(self.conn, "reader", advance=True)
        self.conn.rollback()
        self.assertTrue(s.inbox(self.conn, "reader"))

    def test_invalid_lease_is_rejected_even_when_queue_is_empty(self):
        page = s.lease_inbox(self.conn, "reader")
        s.ack_inbox(self.conn, page["token"], "reader")
        with self.assertRaises(s.SwarmError):
            s.lease_inbox(self.conn, "reader", lease_seconds=0)


if __name__ == "__main__":
    unittest.main()
