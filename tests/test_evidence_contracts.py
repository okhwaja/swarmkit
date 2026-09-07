"""Implementation can bind a newly produced revision without replacing a pinned target."""

from pathlib import Path
import tempfile
import unittest

import swarmctl as s


class EvidenceContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-contract-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Improve latency", ["Verified"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)
        self.task = s.add_task(
            self.conn,
            "Implement",
            "Improve latency",
            "implementation",
            ["Latency measured"],
            [],
            50,
            "manager",
            True,
        )

    def test_owner_can_bind_first_contract_to_newly_produced_revision(self):
        s.configure_runtime(self.conn, {}, strict_evidence=True)
        s.claim_task(self.conn, self.task, "worker", 60)
        s.set_contract(self.conn, self.task, "jj:result-42", "benchmark-host", "worker")
        result = self.root.parent / "benchmark.log"
        result.write_text("Measured latency: 10ms")
        s.record_evidence(
            self.conn,
            self.task,
            "worker",
            "Latency measured",
            "jj:result-42",
            "benchmark-host",
            "benchmark",
            0,
            result,
        )
        s.complete_task(self.conn, self.task, "worker", "Latency improved", ["Measured"], [])
        self.assertEqual(s.task_row(self.conn, self.task)["status"], "DONE")

    def test_active_worker_cannot_replace_preassigned_revision(self):
        s.set_contract(self.conn, self.task, "reviewed-revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 60)
        with self.assertRaises(s.SwarmError):
            s.set_contract(self.conn, self.task, "different-revision", "host", "worker")
        self.assertEqual(
            self.conn.execute(
                "SELECT revision FROM task_contracts WHERE task_id=?", (self.task,)
            ).fetchone()[0],
            "reviewed-revision",
        )

    def test_stale_owner_cannot_bind_contract(self):
        s.claim_task(self.conn, self.task, "worker", 60)
        with self.assertRaises(s.SwarmError):
            s.set_contract(self.conn, self.task, "revision", "host", "stale-worker")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM task_contracts").fetchone()[0], 0)

    def test_legacy_empty_criteria_cannot_pass_strict_verification(self):
        self.conn.execute("UPDATE tasks SET acceptance_json='[]' WHERE id=?", (self.task,))
        self.conn.commit()
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 60)
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, self.task, "worker", "Claimed success", ["Checked"], [])

    def test_identical_contract_retry_has_no_extra_event(self):
        s.claim_task(self.conn, self.task, "worker", 60)
        s.set_contract(self.conn, self.task, "revision", "host", "worker")
        watermark = self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0]
        s.set_contract(self.conn, self.task, "revision", "host", "worker")
        self.assertEqual(self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0], watermark)
