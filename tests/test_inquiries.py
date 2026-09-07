"""Asking about a closed service case must be an atomic, truthful follow-up."""

from pathlib import Path
import tempfile
import unittest

import swarmctl as s
from swarmkit.cases import open_inquiry


class InquiryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-inquiry-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Handle requests", ["Verified"], [], "SERVICE")
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)
        self.case = s.open_case(
            self.root,
            self.conn,
            "source",
            "request-1",
            "Review",
            "Inspect",
            50,
            "human",
            [],
            ready=True,
        )
        task = self.case["tasks"][0]["id"]
        s.claim_task(self.conn, task, "worker", 60)
        s.complete_task(self.conn, task, "worker", "Finished the original review", ["Checked"], [])

    def test_failed_inquiry_does_not_reopen_case(self):
        s.configure_runtime(self.conn, {"max_tasks": 1})
        watermark = self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0]
        with self.assertRaises(s.SwarmError):
            open_inquiry(self.conn, "What happened?", case_id=self.case["id"])
        self.assertEqual(s.case_row(self.conn, self.case["id"])["status"], "DONE")
        self.assertEqual(s.workstream_row(self.conn, self.case["workstream_id"])["status"], "DONE")
        self.assertEqual(self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0], watermark)

    def test_followup_clears_stale_completion_and_creates_briefing(self):
        task = open_inquiry(self.conn, "What happened?", case_id=self.case["id"])
        case = s.case_row(self.conn, self.case["id"])
        self.assertEqual(case["status"], "ACTIVE")
        self.assertIsNone(case["result_summary"])
        self.assertIsNone(case["completion_outcome"])
        self.assertEqual(s.task_row(self.conn, task)["kind"], "briefing")
