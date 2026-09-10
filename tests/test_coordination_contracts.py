"""Durable coordination boundaries: consent, planning, retries and contract changes."""

import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import (
    attention,
    coordination,
    decisions,
    schema,
    tasks,
)


class CoordinationContractsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-contracts-")
        self.base = Path(self.temp.name)
        self.root = self.base / ".swarm"
        s.initialize(self.root, "Coordinate reliably", ["Verified"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def task(self, title="Inspect", ready=True, dependencies=None):
        return s.add_task(
            self.conn,
            title,
            "Inspect safely",
            "discovery",
            ["Checked"],
            dependencies or [],
            50,
            "manager",
            ready,
        )

    def decision(self, resolved=True):
        task = self.task()
        agent = "worker-" + task
        s.claim_task(self.conn, task, agent, 600)
        decision = s.block_task(
            self.conn, task, agent, "human_decision", "Proceed?", "Proceed", ["Proceed", "Wait"]
        )
        if resolved:
            s.resolve_decision(self.conn, decision, "Proceed with checks", "human", "Proceed")
        return task, decision

    def review(self, agent="manager-first", urgency="NORMAL"):
        identifier = s.request_manager_review(
            self.conn, "inspect", "mission", s.mission(self.conn)["id"], urgency
        )[0]
        return s.claim_manager_review(self.conn, agent, 600), identifier

    def config(self, command, max_parallel=2):
        path = self.root / "runner.json"
        data = json.loads(path.read_text())
        data.update(
            command=command,
            working_directory=str(self.base),
            max_parallel=max_parallel,
            scheduler_poll_seconds=0.01,
            manager_review_debounce_seconds=0,
        )
        path.write_text(json.dumps(data))

    def test_prose_revision_preserves_choice_and_records_operation(self):
        _, decision = self.decision()
        s.revise_decision(self.conn, decision, "Proceed after review", "human")
        self.assertEqual(s.require_decision_choice(self.conn, decision, "Proceed")["version"], 3)
        event = self.conn.execute(
            "SELECT payload_json FROM events WHERE event_type='DECISION_REVISED'"
        ).fetchone()
        payload = json.loads(event[0])
        self.assertEqual(
            (payload["choice_operation"], payload["previous_selected_option"]),
            ("preserve", "Proceed"),
        )

    def test_choice_clear_and_set_are_explicit_and_atomic(self):
        _, decision = self.decision()
        with self.assertRaises(s.SwarmError):
            decisions.revise_decision(self.conn, decision, "Change", "human", "Wait", True)
        s.require_decision_choice(self.conn, decision, "Proceed")
        decisions.revise_decision(
            self.conn, decision, "Withdraw structured option", "human", clear_choice=True
        )
        with self.assertRaises(s.SwarmError):
            s.require_decision_choice(self.conn, decision, "Proceed")
        s.revise_decision(self.conn, decision, "Wait", "human", "Wait")
        with mock.patch.object(decisions, "add_event", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                s.revise_decision(self.conn, decision, "Proceed", "human", "Proceed")
        s.require_decision_choice(self.conn, decision, "Wait")

    def test_concurrent_prose_revisions_never_clear_the_choice(self):
        _, decision = self.decision()

        def revise(index):
            conn = s.connect(self.root)
            try:
                return s.revise_decision(conn, decision, "Clarification %d" % index, "human")
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            versions = list(pool.map(revise, range(4)))
        self.assertEqual(sorted(versions), [3, 4, 5, 6])
        s.require_decision_choice(self.conn, decision, "Proceed")

    def test_reference_does_not_gate_or_interrupt_and_survives_cancellation(self):
        source, decision = self.decision(False)
        target = self.task("Independent")
        s.claim_task(self.conn, target, "independent", 600)
        self.assertTrue(decisions.reference_decision(self.conn, decision, target, "manager"))
        self.assertFalse(decisions.reference_decision(self.conn, decision, target, "manager"))
        self.assertEqual(s.task_row(self.conn, target)["owner"], "independent")
        s.cancel_task(self.conn, target, "human", "No longer useful")
        self.assertEqual(s.decision_row(self.conn, decision)["status"], "OPEN")
        self.assertEqual(s.task_row(self.conn, source)["status"], "BLOCKED")

    def test_reference_revision_does_not_retire_its_worker(self):
        _, decision = self.decision()
        target = self.task("Independent")
        s.claim_task(self.conn, target, "independent", 600)
        decisions.reference_decision(self.conn, decision, target, "manager")
        s.revise_decision(self.conn, decision, "Wait", "human", "Wait")
        s.checkpoint_task(self.conn, target, "independent", "Still working", "Continue", 600)

    def test_failed_review_backoff_survives_restart_and_urgency(self):
        review, identifier = self.review(urgency="URGENT")
        s.finish_manager_review(self.conn, identifier, review["owner"], False)
        self.conn.close()
        self.conn = s.connect(self.root)
        self.addCleanup(self.conn.close)
        self.assertIsNone(s.claim_manager_review(self.conn, "next-manager", 600))
        row = self.conn.execute(
            "SELECT * FROM manager_reviews WHERE id=?", (identifier,)
        ).fetchone()
        self.assertEqual(row["failure_count"], 1)
        self.assertIsNotNone(row["next_eligible_at"])
        s.request_manager_review(self.conn, "new finding", "task", "other", "URGENT")
        self.assertIsNone(s.claim_manager_review(self.conn, "next-manager", 600))

    def test_retry_circuit_blocks_new_runs_until_explicit_reset(self):
        self.config([sys.executable, "-c", "raise SystemExit(1)"])
        review, identifier = self.review()
        for index in range(3):
            s.finish_manager_review(self.conn, identifier, review["owner"], False)
            if index < 2:
                self.conn.execute(
                    "UPDATE manager_reviews SET next_eligible_at='2000-01-01T00:00:00Z'"
                )
                self.conn.commit()
                review = s.claim_manager_review(self.conn, "retry-%d" % index, 600)
        self.assertEqual(s.run_loop(self.root, 20)["state"], "ESCALATED")
        self.assertEqual(s.serve(self.root, 3, 0.01, 20)["polls"], 1)
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, self.task(), "worker", 600)
        coordination.retry_manager_review(self.conn, identifier, "human", "Corrected harness")
        self.assertIsNotNone(s.claim_manager_review(self.conn, "repaired-manager", 600))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM review_attempts").fetchone()[0], 4)

    def test_late_manager_completion_cannot_finish_a_new_attempt(self):
        review, identifier = self.review()
        s.finish_manager_review(self.conn, identifier, review["owner"], False)
        coordination.retry_manager_review(self.conn, identifier, "human", "Retry")
        s.claim_manager_review(self.conn, "fresh-manager", 600)
        self.assertFalse(s.finish_manager_review(self.conn, identifier, review["owner"], True))
        with self.assertRaises(s.SwarmError):
            s.commit_review(
                self.conn,
                identifier,
                review["owner"],
                [{"disposition": "no-change", "rationale": "Old"}],
                "Old",
            )
        self.assertEqual(
            self.conn.execute("SELECT owner FROM manager_reviews").fetchone()[0], "fresh-manager"
        )

    def test_failed_subprocess_returns_scheduled_retry_without_spinning(self):
        self.config([sys.executable, "-c", "raise SystemExit(7)"])
        result = s.run_loop(self.root, 200)
        self.assertEqual(result["state"], "WAITING_FOR_REVIEW")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0], 1)
        self.assertIsNotNone(result["next_check_at"])

    def test_plan_publication_is_atomic_and_failed_plans_stay_staged(self):
        committed = self.task("Committed")
        review, identifier = self.review()
        staged = self.task("Staged")
        s.claim_task(self.conn, committed, "worker", 600)
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, staged, "too-early", 600)
        s.finish_manager_review(self.conn, identifier, review["owner"], False)
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, staged, "still-too-early", 600)
        coordination.retry_manager_review(self.conn, identifier, "human", "Adopt reviewed work")
        s.claim_manager_review(self.conn, "new-manager", 600)
        with mock.patch.object(coordination, "add_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                s.finish_manager_review(self.conn, identifier, "new-manager", True)
        self.assertIsNotNone(
            self.conn.execute("SELECT 1 FROM staged_tasks WHERE task_id=?", (staged,)).fetchone()
        )
        s.finish_manager_review(self.conn, identifier, "new-manager", True)
        s.claim_task(self.conn, staged, "after-publication", 600)

    def test_cooldown_does_not_block_committed_work_or_urgent_reviews(self):
        review, identifier = self.review()
        s.finish_manager_review(self.conn, identifier, review["owner"], True)
        ready = self.task()
        s.request_manager_review(self.conn, "ordinary", "task", ready)
        self.assertIsNone(
            s.claim_manager_review(self.conn, "cooldown", 600, min_interval_seconds=300)
        )
        s.claim_task(self.conn, ready, "worker", 600)
        s.request_manager_review(self.conn, "urgent", "task", ready, "URGENT")
        self.assertIsNotNone(
            s.claim_manager_review(self.conn, "urgent-manager", 600, min_interval_seconds=300)
        )

    def test_real_manager_can_wait_for_committed_worker_without_exposing_staged_work(self):
        committed = self.task("Committed")
        harness = self.base / "harness.py"
        harness.write_text(
            """import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import swarmctl as s
root, role, agent, task = Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
c = s.connect(root)
marker = root / "worker-finished"
if role == "manager":
    if not c.execute("SELECT 1 FROM tasks WHERE title='Staged'").fetchone():
        s.add_task(c, 'Staged', 'New plan', 'discovery', ['Checked'], [], 50, agent, True)
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    if not marker.exists(): raise SystemExit(9)
    if c.execute("SELECT generation FROM tasks WHERE title='Staged'").fetchone()[0] != 0:
        raise SystemExit(10)
else:
    s.complete_task(c, task, agent, 'Done', ['Checked'], [])
    marker.write_text('done')
c.close()
"""
        )
        self.config(
            [
                sys.executable,
                "-B",
                str(harness),
                str(Path(s.__file__).parent),
                "{root}",
                "{role}",
                "{agent_id}",
                "{task_id}",
            ]
        )
        result = s.run_loop(self.root, 2)
        self.assertEqual(result["state"], "MAX_CYCLES")
        self.assertEqual(s.task_row(self.conn, committed)["status"], "DONE")
        self.assertEqual([run["exit_code"] for run in result["runs"]], [0, 0])
        staged = self.conn.execute(
            "SELECT id,generation FROM tasks WHERE title='Staged'"
        ).fetchone()
        self.assertEqual(staged["generation"], 0)
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM staged_tasks WHERE task_id=?", (staged["id"],)
            ).fetchone()
        )

    def test_attention_ages_once_and_reenters_after_unblocking(self):
        task, decision = self.decision(False)
        s.configure_runtime(self.conn, {"decision_escalation_seconds": 60})
        self.conn.execute(
            "UPDATE decisions SET created_at='2000-01-01T00:00:00Z' WHERE id=?", (decision,)
        )
        self.conn.commit()
        for _ in range(3):
            s.reconcile_conn(self.conn)
        count = lambda event: self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type=?", (event,)
        ).fetchone()[0]
        self.assertEqual(count("DECISION_AGING"), 1)
        self.assertEqual(count("MISSION_BLOCKED_ON_HUMAN"), 1)
        self.assertGreater(attention.decision_attention(self.conn)[0]["age_seconds"], 60)
        independent = self.task("Independent")
        self.assertEqual(count("HUMAN_BLOCK_CLEARED"), 1)
        s.cancel_task(self.conn, independent, "human", "Finished elsewhere")
        self.assertEqual(count("MISSION_BLOCKED_ON_HUMAN"), 2)
        self.assertEqual(s.decision_row(self.conn, decision)["status"], "OPEN")
        board = Path(s.render_board(self.root)).read_text()
        self.assertIn(decision, board.split("## Needs attention")[1].split("## ")[0])

    def test_attention_read_preserves_callers_transaction(self):
        _, decision = self.decision(False)
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE decisions SET question='Pending edit' WHERE id=?", (decision,))
        self.assertEqual(attention.decision_attention(self.conn)[0]["question"], "Pending edit")
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertEqual(s.decision_row(self.conn, decision)["question"], "Proceed?")

    def test_amendment_retains_identity_history_and_requires_fresh_approval(self):
        task = self.task(ready=False)
        child = self.task("Dependent", dependencies=[task])
        version = tasks.amend_task_acceptance(
            self.conn, task, ["New check"], 1, "New evidence", "human", "change-1"
        )
        self.assertEqual(version, 2)
        self.assertEqual(
            tasks.amend_task_acceptance(
                self.conn, task, ["New check"], 1, "New evidence", "human", "change-1"
            ),
            2,
        )
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, task, "early", 600)
        s.approve_task(self.conn, task, "human")
        s.claim_task(self.conn, task, "fresh", 600)
        self.assertEqual(s.attempt_for_task(self.conn, task)["acceptance_revision"], 2)
        self.assertEqual(s.task_row(self.conn, task)["generation"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT depends_on FROM task_dependencies WHERE task_id=?", (child,)
            ).fetchone()[0],
            task,
        )

    def test_amendment_rejects_live_work_wrong_version_and_rolls_back(self):
        task = self.task()
        with self.assertRaises(s.SwarmError):
            tasks.amend_task_acceptance(self.conn, task, ["New"], 2, "Change", "human", "wrong")
        with mock.patch.object(tasks, "add_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                tasks.amend_task_acceptance(
                    self.conn, task, ["New"], 1, "Change", "human", "rollback"
                )
        self.assertEqual(s.task_row(self.conn, task)["acceptance_revision"], 1)
        s.claim_task(self.conn, task, "worker", 600)
        with self.assertRaises(s.SwarmError):
            tasks.amend_task_acceptance(self.conn, task, ["New"], 1, "Change", "human", "live")

    def test_old_evidence_cannot_satisfy_an_amended_contract(self):
        task = self.task()
        s.claim_task(self.conn, task, "old-worker", 600)
        s.set_contract(self.conn, task, "revision", "host", "old-worker")
        result = self.base / "result.txt"
        result.write_text("Passed")
        old = s.record_evidence(
            self.conn,
            task,
            "old-worker",
            "Checked",
            "revision",
            "host",
            "check",
            0,
            result,
            "record-1",
        )
        self.conn.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (task,))
        self.conn.commit()
        s.reconcile_conn(self.conn)
        tasks.amend_task_acceptance(
            self.conn, task, ["Checked", "Additional"], 1, "Add coverage", "human", "change"
        )
        s.approve_task(self.conn, task, "human")
        s.claim_task(self.conn, task, "new-worker", 600)
        self.assertTrue(s.evidence_gaps(self.conn, task))
        self.assertIsNotNone(
            self.conn.execute("SELECT 1 FROM evidence WHERE id=?", (old,)).fetchone()
        )
        with self.assertRaises(s.SwarmError):
            s.record_evidence(
                self.conn,
                task,
                "new-worker",
                "Checked",
                "revision",
                "host",
                "check",
                0,
                result,
                "record-1",
            )

    def test_schema_twelve_upgrade_is_transactional(self):
        self.conn.execute("UPDATE meta SET value='12' WHERE key='schema_version'")
        self.conn.commit()
        with mock.patch.object(
            schema, "migrate_coordination", side_effect=RuntimeError("migration failed")
        ):
            with self.assertRaises(RuntimeError):
                schema.ensure_schema(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            "12",
        )
        schema.ensure_schema(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            s.SCHEMA_VERSION,
        )

    def test_plan_edit_after_strict_commit_requires_another_commit(self):
        s.configure_runtime(self.conn, {}, True)
        review, identifier = self.review()
        self.task("First staged task")
        s.commit_review(
            self.conn,
            identifier,
            review["owner"],
            [{"disposition": "acted", "rationale": "Created work"}],
            "Plan ready",
        )
        second = self.task("Later task")
        self.assertFalse(s.finish_manager_review(self.conn, identifier, review["owner"], True))
        self.assertIsNotNone(
            self.conn.execute("SELECT 1 FROM staged_tasks WHERE task_id=?", (second,)).fetchone()
        )

    def test_live_manager_cannot_publish_before_its_process_exits(self):
        review, identifier = self.review()
        staged = self.task()
        self.conn.execute(
            "INSERT INTO agent_runs(id,mission_id,role,agent_id,prompt_path,command_json,started_at) VALUES(?,?,?,?,?,?,?)",
            (
                "live-review",
                s.mission(self.conn)["id"],
                "manager",
                review["owner"],
                "prompt",
                "[]",
                s.utcnow(),
            ),
        )
        self.conn.commit()
        self.assertFalse(s.finish_manager_review(self.conn, identifier, review["owner"], True))
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, staged, "worker", 600)

    def test_cancellation_and_new_decision_gate_invalidate_committed_work(self):
        task = self.task()
        _, decision = self.decision(False)
        self.review()
        s.link_decision(self.conn, decision, task, "human")
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, task, "worker", 600)
        other = self.task("Other")
        s.cancel_task(self.conn, other, "human", "Invalidated")
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, other, "another-worker", 600)

    def test_concurrent_amendments_have_one_winner(self):
        task = self.task(ready=False)

        def amend(index):
            conn = s.connect(self.root)
            try:
                try:
                    return tasks.amend_task_acceptance(
                        conn, task, ["Check %d" % index], 1, "Updated", "human", "key-%d" % index
                    )
                except s.SwarmError:
                    return None
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(amend, range(4)))
        self.assertEqual(outcomes.count(2), 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM acceptance_revisions").fetchone()[0], 1
        )

    def test_real_legacy_schema_upgrade_preserves_data_and_rolls_back_ddl(self):
        import sqlite3

        legacy = self.base / "legacy"
        legacy.mkdir()
        conn = sqlite3.connect(str(legacy / "state.sqlite3"))
        self.addCleanup(conn.close)
        for source in (
            schema.SCHEMA,
            schema.RUNTIME_SCHEMA,
            schema.CONTEXT_SCHEMA,
            schema.WORKSPACE_CREATION_SCHEMA,
            schema.REVIEW_BATCH_SCHEMA,
            schema.EVIDENCE_SCHEMA,
        ):
            schema.execute_schema(conn, source)
        schema.migrate_workspace_schema(conn)
        conn.execute("INSERT INTO meta VALUES('schema_version','12')")
        conn.execute(
            "INSERT INTO missions(id,objective,success_json,constraints_json,created_at,updated_at) VALUES('M','Legacy','[]','[]',?,?)",
            (s.utcnow(), s.utcnow()),
        )
        conn.execute(
            "INSERT INTO tasks(id,mission_id,title,description,kind,acceptance_json,created_at,updated_at) VALUES('T','M','Legacy task','Keep history','discovery','[\"Checked\"]',?,?)",
            (s.utcnow(), s.utcnow()),
        )
        conn.execute(
            "INSERT INTO manager_reviews(id,mission_id,status,triggers_json,owner,started_at,requested_at,lease_until,created_at,updated_at) VALUES('MR','M','RUNNING','[]','legacy-manager',?,?,'2099-01-01T00:00:00Z',?,?)",
            (s.utcnow(),) * 4,
        )
        conn.commit()
        real_execute = schema.execute_schema

        def fail_after_alters(connection, source):
            if source == schema.COORDINATION_SCHEMA:
                raise RuntimeError("Crash after ALTER")
            return real_execute(connection, source)

        with mock.patch.object(schema, "execute_schema", side_effect=fail_after_alters):
            with self.assertRaises(RuntimeError):
                schema.ensure_schema(conn)
        self.assertNotIn(
            "acceptance_revision", {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        )
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "12"
        )
        schema.ensure_schema(conn)
        self.assertEqual(
            conn.execute("SELECT acceptance_revision FROM tasks WHERE id='T'").fetchone()[0], 1
        )
        self.assertEqual(
            conn.execute("SELECT agent,generation FROM review_attempts").fetchone(),
            ("legacy-manager", 1),
        )
        self.assertEqual(
            conn.execute("SELECT lease_until FROM manager_reviews").fetchone()[0],
            "2099-01-01T00:00:00Z",
        )
        self.assertEqual(
            conn.execute("SELECT task_id,review_id FROM staged_tasks").fetchone(), ("T", "MR")
        )
