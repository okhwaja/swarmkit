"""Operator views observe one commit and never publish unrelated derived reports."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import cli, core, queries, views


class ConsistentReadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-read-snapshot-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Observe one state", ["Consistent"], [], "SERVICE")
        self.conn = s.connect(self.root)
        self.writer = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.writer.close)
        self.case = s.open_case(
            self.root,
            self.conn,
            "provider",
            "event-1",
            "Inspect",
            "Verify",
            50,
            "ingress",
            ["Checked"],
            ready=True,
        )
        self.task = self.case["tasks"][0]["id"]

    def test_snapshot_does_not_mix_tasks_and_case_state_across_a_concurrent_commit(self):
        original = queries.task_dict
        changed = False

        def cancel_between_queries(conn, row, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                s.cancel_case(self.writer, self.case["id"], "human", "No longer needed")
            return original(conn, row, **kwargs)

        with mock.patch.object(queries, "task_dict", side_effect=cancel_between_queries):
            snapshot = s.mission_snapshot(self.conn)
        self.assertTrue(changed)
        self.assertEqual(snapshot["tasks"][0]["status"], "READY")
        self.assertEqual(snapshot["cases"][0]["status"], "ACTIVE")
        self.assertEqual(snapshot["workstreams"][0]["status"], "ACTIVE")
        self.assertEqual(s.case_row(self.conn, self.case["id"])["status"], "CANCELLED")
        self.assertFalse(self.conn.in_transaction)

    def test_nested_snapshot_does_not_commit_or_rollback_callers_work(self):
        self.conn.execute("UPDATE missions SET objective='Uncommitted objective'")
        snapshot = s.mission_snapshot(self.conn)
        self.assertEqual(snapshot["mission"]["objective"], "Uncommitted objective")
        self.assertTrue(self.conn.in_transaction)
        self.assertEqual(s.mission(self.writer)["objective"], "Observe one state")
        self.conn.rollback()
        self.assertEqual(s.mission(self.conn)["objective"], "Observe one state")

    def test_failed_projection_releases_only_its_own_snapshot(self):
        with mock.patch.object(queries, "task_dict", side_effect=RuntimeError("projection failed")):
            with self.assertRaisesRegex(RuntimeError, "projection failed"):
                s.mission_snapshot(self.conn)
        self.assertFalse(self.conn.in_transaction)
        with core.read_snapshot(self.conn):
            with self.assertRaises(RuntimeError):
                with core.read_snapshot(self.conn):
                    raise RuntimeError("nested read failed")
            self.assertTrue(self.conn.in_transaction)
        self.assertFalse(self.conn.in_transaction)

    def test_report_health_and_snapshot_share_the_same_database_version(self):
        original = views.mission_snapshot

        def change_after_snapshot(conn):
            result = original(conn)
            # A deliberately incomplete external mutation would trigger doctor if
            # it read a newer version than the report's task snapshot.
            self.writer.execute(
                "UPDATE tasks SET status='CLAIMED',owner=NULL,lease_until=NULL WHERE id=?",
                (self.task,),
            )
            self.writer.commit()
            return result

        with mock.patch.object(views, "mission_snapshot", side_effect=change_after_snapshot):
            report = s.render_status_report(self.root)
        self.assertNotIn("active task has no owner", report.read_text())
        self.assertFalse(s.doctor(self.conn)["ok"])

    def test_read_commands_do_not_regenerate_whole_mission_reports(self):
        commands = [
            ["case", "show", self.case["id"]],
            ["case", "list"],
            ["task", "show", self.task],
            ["task", "list"],
            ["workstream", "show", self.case["workstream_id"]],
            ["workstream", "list"],
            ["policy", "list"],
            ["policy", "applications"],
            ["extension", "list"],
            ["delivery", "list"],
            ["finding", "list"],
            ["wait", "list"],
            ["decision", "list"],
            ["fact", "list"],
        ]
        with (
            mock.patch.object(
                cli, "render_board", side_effect=AssertionError("Unrequested board write")
            ),
            mock.patch.object(
                cli, "render_status_report", side_effect=AssertionError("Unrequested report write")
            ),
        ):
            for command in commands:
                with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(s.main(["--root", str(self.root)] + command), 0)


if __name__ == "__main__":
    unittest.main()
