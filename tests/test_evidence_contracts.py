"""Implementation can bind a newly produced revision without replacing a pinned target."""

from pathlib import Path
import contextlib
import concurrent.futures
import io
import json
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
        idempotency_key=None,
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
            idempotency_key,
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

    def test_status_explains_missing_stale_failed_changed_and_unavailable_results(self):
        self.assertEqual(
            evidence.evidence_status(self.conn, self.task)["gaps"],
            ["No revision/environment contract"],
        )
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        self.assertEqual(
            evidence.evidence_status(self.conn, self.task)["criteria"][0]["status"], "MISSING"
        )
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        self.record(path, revision="wrong-revision")
        stale = evidence.evidence_status(self.conn, self.task)["criteria"][0]
        self.assertEqual(stale["status"], "STALE")
        self.assertIn("revision", stale["reason"])
        failed = self.record(path, exit_code=3)
        state = evidence.evidence_status(self.conn, self.task)["criteria"][0]
        self.assertEqual(state["status"], "FAILED")
        self.assertEqual(state["evidence"]["id"], failed)
        self.assertIn("3", state["reason"])
        self.record(path)
        self.assertEqual(
            evidence.evidence_status(self.conn, self.task)["criteria"][0]["status"], "PASSED"
        )
        path.write_text("Changed")
        self.assertEqual(
            evidence.evidence_status(self.conn, self.task)["criteria"][0]["status"], "FILE_CHANGED"
        )
        path.unlink()
        self.assertEqual(
            evidence.evidence_status(self.conn, self.task)["criteria"][0]["status"],
            "FILE_UNAVAILABLE",
        )

    def test_status_distinguishes_previous_attempt_and_mission_revision(self):
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        self.record(path)
        self.conn.execute("UPDATE tasks SET generation=generation+1 WHERE id=?", (self.task,))
        self.conn.execute("UPDATE runtime_state SET revision=revision+1")
        self.conn.commit()
        result = evidence.evidence_status(self.conn, self.task)
        self.assertEqual(result["criteria"][0]["status"], "STALE")
        self.assertEqual(
            result["criteria"][0]["reason"],
            "Latest record differs in: generation, mission_revision",
        )

    def test_evidence_history_is_stable_across_same_timestamp_records_and_new_insertions(self):
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        ids = [self.record(path) for _ in range(5)]
        self.conn.execute("UPDATE evidence SET created_at='2026-01-01T00:00:00Z'")
        self.conn.commit()
        first = evidence.evidence_history(self.conn, self.task, 2)
        self.assertEqual([row["id"] for row in first["records"]], list(reversed(ids[3:])))
        self.record(path)
        second = evidence.evidence_history(self.conn, self.task, 2, first["next_before"])
        third = evidence.evidence_history(self.conn, self.task, 2, second["next_before"])
        self.assertEqual(
            [row["id"] for row in second["records"] + third["records"]], list(reversed(ids[:3]))
        )
        self.assertIsNone(third["next_before"])
        for limit in (0, 501):
            with self.assertRaises(s.SwarmError):
                evidence.evidence_history(self.conn, self.task, limit)
        with self.assertRaises(s.SwarmError):
            evidence.evidence_history(self.conn, self.task, before="missing")
        for command in (["evidence", "show"], ["evidence", "list", "--limit", "2"]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(
                    s.main(["--root", str(self.root)] + command + ["--task", self.task]), 0
                )
            json.loads(output.getvalue())

    def test_indexed_status_does_not_scan_verification_history(self):
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        self.record(path)
        row = tuple(self.conn.execute("SELECT * FROM evidence").fetchone())
        self.conn.executemany(
            "INSERT INTO evidence(id,task_id,generation,mission_revision,criterion,revision,environment,command,exit_code,path,sha256,created_at,acceptance_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (("old-%s" % i,) + row[1:] for i in range(10000)),
        )
        self.conn.commit()
        steps = []
        self.conn.set_progress_handler(lambda: steps.append(1) or 0, 100)
        try:
            self.assertEqual(evidence.evidence_status(self.conn, self.task)["gaps"], [])
            evidence.evidence_history(self.conn, self.task, 2)
        finally:
            self.conn.set_progress_handler(None, 0)
        self.assertLess(
            len(steps), 20, "Lookup walked historical records instead of selecting indexed results"
        )

    def test_schema_eleven_upgrade_preserves_evidence_and_adds_lookup_indexes(self):
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        recorded = self.record(path)
        indexes = ("idx_evidence_target", "idx_evidence_criterion", "idx_evidence_task")
        for index in indexes:
            self.conn.execute("DROP INDEX " + index)
        self.conn.execute("DROP TABLE evidence_record_keys")
        self.conn.execute("UPDATE meta SET value='11' WHERE key='schema_version'")
        self.conn.commit()
        upgraded = s.connect(self.root)
        try:
            self.assertEqual(
                upgraded.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                s.SCHEMA_VERSION,
            )
            self.assertEqual(upgraded.execute("SELECT id FROM evidence").fetchone()[0], recorded)
            for index in indexes:
                self.assertIsNotNone(
                    upgraded.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (index,)
                    ).fetchone()
                )
        finally:
            upgraded.close()

    def test_retrying_old_success_does_not_supersede_a_later_failed_check(self):
        s.set_contract(self.conn, self.task, "revision", "host", "manager")
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        original = self.record(path, idempotency_key="measurement-1")
        self.record(path, exit_code=1, idempotency_key="measurement-2")
        counts = tuple(
            self.conn.execute(
                "SELECT (SELECT COUNT(*) FROM evidence),(SELECT COUNT(*) FROM artifacts),(SELECT COUNT(*) FROM events)"
            ).fetchone()
        )
        self.assertEqual(self.record(path, idempotency_key="measurement-1"), original)
        self.assertEqual(
            tuple(
                self.conn.execute(
                    "SELECT (SELECT COUNT(*) FROM evidence),(SELECT COUNT(*) FROM artifacts),(SELECT COUNT(*) FROM events)"
                ).fetchone()
            ),
            counts,
        )
        self.assertEqual(s.evidence_gaps(self.conn, self.task), ["Latency measured"])
        with self.assertRaises(s.SwarmError):
            self.record(path, exit_code=1, idempotency_key="measurement-1")
        path.write_text("Different measurement")
        with self.assertRaises(s.SwarmError):
            self.record(path, idempotency_key="measurement-1")

    def test_concurrent_evidence_retries_create_one_record_and_artifact(self):
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")

        def record(_):
            conn = s.connect(self.root)
            try:
                return s.record_evidence(
                    conn,
                    self.task,
                    "worker",
                    "Latency measured",
                    "revision",
                    "host",
                    "benchmark",
                    0,
                    path,
                    "check-1",
                )
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(pool.map(record, range(6)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 1)

    def test_evidence_key_rolls_back_with_record_and_artifact(self):
        s.claim_task(self.conn, self.task, "worker", 600)
        path = self.root.parent / "result.log"
        path.write_text("Measured")
        with mock.patch.object(evidence, "add_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                self.record(path, idempotency_key="check-1")
        for table in ("evidence", "evidence_record_keys", "artifacts"):
            self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0)
        args = [
            "--root",
            str(self.root),
            "evidence",
            "record",
            "--task",
            self.task,
            "--agent",
            "worker",
            "--criterion",
            "Latency measured",
            "--revision",
            "revision",
            "--environment",
            "host",
            "--command",
            "benchmark",
            "--exit-code",
            "0",
            "--path",
            str(path),
            "--idempotency-key",
            "check-1",
        ]
        recorded = []
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(s.main(args), 0)
            recorded.append(json.loads(output.getvalue())["evidence_id"])
        self.assertEqual(recorded[0], recorded[1])

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
