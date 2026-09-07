"""Implementation can bind a newly produced revision without replacing a pinned target."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from swarmkit import evidence, storage

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

    def record(
        self,
        path,
        exit_code=0,
        criterion="Latency measured",
        revision="revision",
        environment="host",
    ):
        return s.record_evidence(
            self.conn,
            self.task,
            "worker",
            criterion,
            revision,
            environment,
            "benchmark",
            exit_code,
            path,
        )

    def test_failed_rerun_supersedes_prior_pass_until_new_success(self):
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        passing = self.root.parent / "pass.log"
        passing.write_text("Pass")
        failing = self.root.parent / "fail.log"
        failing.write_text("Regression found")
        self.record(passing)
        self.assertEqual(s.evidence_gaps(self.conn, self.task), [])
        self.record(failing, exit_code=1)
        self.assertEqual(s.evidence_gaps(self.conn, self.task), ["Latency measured"])
        with self.assertRaisesRegex(s.SwarmError, "evidence"):
            s.complete_task(self.conn, self.task, "worker", "Claimed fixed", ["Checked"], [])
        self.record(passing)
        self.assertEqual(s.evidence_gaps(self.conn, self.task), [])

    def test_newer_evidence_for_other_target_does_not_supersede_contracted_target(self):
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        self.record(path)
        self.record(path, exit_code=1, revision="other-revision")
        self.record(path, exit_code=1, environment="other-host")
        self.assertEqual(s.evidence_gaps(self.conn, self.task), [])

    def test_artifact_and_evidence_share_one_observation_even_if_file_changes(self):
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Original result")
        actual_hash = storage.hash_file

        def change_after_hash(value):
            result = actual_hash(value)
            path.write_text("Changed result after hashing")
            return result

        with mock.patch.object(storage, "hash_file", side_effect=change_after_hash) as hashed:
            evidence_id = self.record(path)
        self.assertEqual(hashed.call_count, 1)
        row = self.conn.execute("SELECT sha256 FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        artifact = self.conn.execute(
            "SELECT sha256 FROM artifacts WHERE note=?", ("Evidence " + evidence_id,)
        ).fetchone()
        self.assertEqual(row[0], artifact[0])
        self.assertEqual(s.evidence_gaps(self.conn, self.task), ["Latency measured"])

    def test_shared_result_is_hashed_once_per_completion_check(self):
        self.conn.execute(
            "UPDATE tasks SET acceptance_json=? WHERE id=?",
            (s.json_dump(["Latency measured", "Throughput measured"]), self.task),
        )
        self.conn.commit()
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Latency and throughput measured")
        self.record(path)
        self.record(path, criterion="Throughput measured")
        with mock.patch.object(evidence, "hash_file", wraps=evidence.hash_file) as hashed:
            self.assertEqual(s.evidence_gaps(self.conn, self.task), [])
        self.assertEqual(hashed.call_count, 1)
        path.unlink()
        self.assertEqual(
            s.evidence_gaps(self.conn, self.task), ["Latency measured", "Throughput measured"]
        )

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
