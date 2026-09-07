"""Health checks should explain damaged state and stay useful as a service grows."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import core

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_service import active_case_fixture


class DiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-health-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Inspect damaged state", ["Useful diagnosis"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def task(self, stream=None):
        return s.add_task(
            self.conn,
            "Inspect",
            "Inspect",
            "discovery",
            ["Checked"],
            [],
            50,
            "manager",
            True,
            stream,
        )

    def test_malformed_task_and_workstream_fields_return_all_problems_without_writes(self):
        stream = s.add_workstream(self.conn, "Scope", "Outcome", "manager", "ACTIVE")
        task, completed = self.task(stream), self.task()
        self.conn.execute(
            "UPDATE tasks SET status='CLAIMED',owner='worker',lease_until='not-a-time' WHERE id=?",
            (task,),
        )
        self.conn.execute(
            "UPDATE tasks SET status='DONE',verification_json='{' WHERE id=?", (completed,)
        )
        self.conn.execute(
            "UPDATE workstreams SET forecast_latest='invalid',status='CANCELLED' WHERE id=?",
            (stream,),
        )
        self.conn.commit()
        changes = self.conn.total_changes
        result = s.doctor(self.conn)
        self.assertFalse(result["ok"])
        problems = {item["problem"] for item in result["problems"]}
        self.assertIn("invalid task lease timestamp", problems)
        self.assertIn("invalid task verification JSON", problems)
        self.assertIn("invalid workstream forecast timestamp", problems)
        self.assertIn("cancelled workstream has non-terminal tasks", problems)
        self.assertEqual(self.conn.total_changes, changes)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(s.main(["--root", str(self.root), "doctor"]), 2)
        self.assertFalse(json.loads(output.getvalue())["ok"])

    def test_malformed_policy_application_is_reported_without_losing_other_checks(self):
        source = Path(s.__file__).parent / "examples/policy-packs/pipeline-repair"
        s.install_policy(self.conn, source, "operator")
        application = s.apply_policy(
            self.conn,
            "pipeline-repair",
            ["goal=Repair", "test_command=check"],
            None,
            "manager",
            True,
        )
        self.conn.execute("UPDATE policy_packs SET manifest_json='['")
        self.conn.execute(
            "UPDATE policy_applications SET manifest_json='null' WHERE id=?", (application["id"],)
        )
        self.conn.commit()
        result = s.doctor(self.conn)
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["entity"] == application["id"] for item in result["problems"]))
        self.assertTrue(any(item["entity"] == "pipeline-repair" for item in result["problems"]))

    def test_claimed_delivery_without_lease_reports_error_instead_of_crashing(self):
        s.install_extension(
            self.conn, Path(s.__file__).parent / "examples/extensions/harness-email", "operator"
        )
        path = self.root.parent / "report.md"
        path.write_text("Report")
        item = s.enqueue_delivery(
            self.root,
            self.conn,
            "harness-email-example",
            "email",
            "Report",
            ["replace-me@example.com"],
            path,
            [],
            "report",
            "operator",
        )
        self.conn.execute(
            "UPDATE deliveries SET status='CLAIMED',claimed_by='sender',lease_until=NULL WHERE id=?",
            (item["id"],),
        )
        self.conn.commit()
        self.assertIn(
            "claimed delivery lacks owner or lease",
            [item["problem"] for item in s.doctor(self.conn)["problems"]],
        )

    def test_file_disappearing_between_check_and_hash_is_an_integrity_failure(self):
        path = self.root.parent / "payload.txt"
        path.write_text("Payload")
        with mock.patch.object(core, "hash_file", side_effect=FileNotFoundError("disappeared")):
            self.assertFalse(core.case_payload_intact(path, "hash", 7))
            self.assertFalse(
                core.delivery_content_intact(
                    {"content_path": path, "content_sha256": "hash", "content_size_bytes": 7}
                )
            )

    def test_matching_titles_in_independent_workstreams_are_not_duplicate_work(self):
        first = s.add_workstream(self.conn, "First case", "Verified", "manager")
        second = s.add_workstream(self.conn, "Second case", "Verified", "manager")
        self.task(first)
        self.task(second)
        self.assertFalse(
            any("duplicate" in item["problem"] for item in s.doctor(self.conn)["problems"])
        )
        self.task(first)
        duplicate = [
            item for item in s.doctor(self.conn)["problems"] if "duplicate" in item["problem"]
        ]
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(duplicate[0]["entity"], first)

    def test_service_health_does_not_add_queries_per_task_or_case(self):
        reads = []
        for count in (2, 200):
            root = self.root.parent / ("service-%s" % count)
            conn = active_case_fixture(s, root, count)
            try:
                queries = []
                conn.set_trace_callback(
                    lambda sql: (
                        queries.append(sql)
                        if sql.lstrip().upper().startswith(("SELECT", "WITH"))
                        else None
                    )
                )
                s.doctor(conn)
                reads.append(len(queries))
            finally:
                conn.close()
        self.assertEqual(reads[0], reads[1])
        self.assertLess(reads[1], 25)


if __name__ == "__main__":
    unittest.main()
