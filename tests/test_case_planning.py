"""Case replanning is one retriable transaction, including old work and approvals."""

import contextlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import cases


class CasePlanningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-case-plan-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Recover pipeline", ["Verified"], [], "SERVICE")
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)
        s.install_policy(
            self.conn, Path(s.__file__).parent / "examples/policy-packs/pipeline-repair", "human"
        )
        self.case = s.open_case(
            self.root,
            self.conn,
            "pipeline",
            "incident-1",
            "Recover",
            "Restore service",
            50,
            "ingress",
            ["Verified"],
            ready=True,
        )
        self.intake = self.case["tasks"][0]["id"]

    def apply(self, conn=None, **changes):
        options = dict(
            case_id=self.case["id"],
            policy_id="pipeline-repair",
            policy_variables=["goal=Restore delivery", "test_command=checks"],
            actor="manager",
            ready=True,
            idempotency_key="incident-plan-v1",
            replace=True,
            reason="Diagnosis supports a structured repair plan",
        )
        options.update(changes)
        return s.apply_policy_to_case(conn or self.conn, **options)

    def snapshot(self):
        return {
            name: [tuple(row) for row in self.conn.execute("SELECT * FROM " + name)]
            for name in (
                "tasks",
                "case_tasks",
                "cases",
                "workstreams",
                "events",
                "policy_applications",
                "policy_application_keys",
                "decisions",
                "decision_tasks",
                "attempts",
            )
        }

    def test_replacement_and_retry_preserve_one_plan_and_original_history(self):
        result = self.apply()
        application = result["applied_policy_application_id"]
        self.assertEqual(s.task_row(self.conn, self.intake)["status"], "CANCELLED")
        self.assertEqual(result["policy_application_id"], application)
        self.assertFalse(result["replayed"])
        before = self.snapshot()
        retry = self.apply(
            actor="fresh-manager", policy_variables=["test_command=checks", "goal=Restore delivery"]
        )
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["applied_policy_application_id"], application)
        self.assertEqual(self.snapshot(), before)
        replacement = self.apply(
            idempotency_key="incident-plan-v2",
            reason="A new diagnosis",
            policy_variables=["goal=Recover backlog", "test_command=checks"],
        )
        old_retry = self.apply()
        self.assertEqual(old_retry["applied_policy_application_id"], application)
        self.assertEqual(old_retry["policy_application_id"], replacement["policy_application_id"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM policy_applications").fetchone()[0], 2
        )

    def test_completed_intake_can_install_policy_with_implicit_initial_retry_identity(self):
        s.claim_task(self.conn, self.intake, "owner", 600)
        s.complete_task(self.conn, self.intake, "owner", "Diagnosis ready", ["Verified"], [])
        result = self.apply(idempotency_key=None, replace=False, reason=None)
        self.assertEqual(s.task_row(self.conn, self.intake)["status"], "DONE")
        s.control_mission(self.conn, "cancel", "human", "Withdrawn")
        before = self.snapshot()
        again = self.apply(idempotency_key=None, replace=False, reason=None)
        self.assertEqual(again["applied_policy_application_id"], result["policy_application_id"])
        self.assertEqual(self.snapshot(), before)

    def test_failed_replacement_rolls_back_cancellations_keys_and_new_graph(self):
        before = self.snapshot()
        with mock.patch.object(cases, "add_event", side_effect=RuntimeError("after cancellation")):
            with self.assertRaisesRegex(RuntimeError, "after cancellation"):
                self.apply()
        self.assertEqual(self.snapshot(), before)
        self.apply()

    def test_invalid_policy_or_conflicting_retry_does_not_retire_work(self):
        before = self.snapshot()
        with self.assertRaisesRegex(s.SwarmError, "required policy variable"):
            self.apply(policy_variables=[])
        self.assertEqual(self.snapshot(), before)
        self.apply()
        before = self.snapshot()
        with self.assertRaisesRegex(s.SwarmError, "different work"):
            self.apply(reason="Changed rationale under same key")
        self.assertEqual(self.snapshot(), before)

    def test_open_and_resolved_decisions_follow_replacement_tasks(self):
        for resolve in (False, True):
            with self.subTest(resolve=resolve):
                # Start from the current ready plan's first task for the second replacement.
                task = (
                    self.intake
                    if not resolve
                    else self.conn.execute(
                        "SELECT t.id FROM tasks t WHERE t.status='READY' ORDER BY rowid LIMIT 1"
                    ).fetchone()[0]
                )
                s.claim_task(self.conn, task, "owner-" + str(resolve), 600)
                decision = s.block_task(
                    self.conn,
                    task,
                    "owner-" + str(resolve),
                    "human_decision",
                    "May repair?",
                    "Inspect",
                    [],
                )
                if resolve:
                    s.resolve_decision(self.conn, decision, "Repair only staging", "human")
                result = self.apply(idempotency_key="decision-" + str(resolve))
                new_tasks = self.conn.execute(
                    "SELECT task_id FROM policy_application_tasks WHERE application_id=?",
                    (result["policy_application_id"],),
                ).fetchall()
                self.assertEqual(
                    s.decision_row(self.conn, decision)["status"], "RESOLVED" if resolve else "OPEN"
                )
                for row in new_tasks:
                    self.assertTrue(
                        self.conn.execute(
                            "SELECT 1 FROM decision_tasks WHERE decision_id=? AND task_id=?",
                            (decision, row[0]),
                        ).fetchone()
                    )
                if not resolve:
                    self.assertFalse(
                        any(s.task_row(self.conn, row[0])["status"] == "READY" for row in new_tasks)
                    )
                    s.resolve_decision(self.conn, decision, "Proceed with staging only", "human")
                    s.reconcile_conn(self.conn)

    def test_external_dependents_require_explicit_replanning(self):
        outside = s.add_task(
            self.conn,
            "Other case",
            "Needs this diagnosis",
            "discovery",
            ["Verified"],
            [self.intake],
            50,
            "manager",
            True,
        )
        before = self.snapshot()
        with self.assertRaisesRegex(s.SwarmError, "outside this case"):
            self.apply()
        self.assertEqual(self.snapshot(), before)
        self.assertNotEqual(s.task_row(self.conn, outside)["status"], "CANCELLED")

    def test_uncertain_effect_and_unclosed_harness_block_replacement(self):
        s.claim_task(self.conn, self.intake, "owner", 600)
        effect = s.prepare_effect(
            self.conn, self.intake, "owner", "restart-1", "staging", "revision", {}
        )
        s.transition_effect(self.conn, effect["id"], "start", "owner")
        with self.assertRaisesRegex(s.SwarmError, "Reconcile"):
            self.apply()
        s.transition_effect(
            self.conn, effect["id"], "not-applied", "operator", "Provider confirms no restart"
        )
        self.conn.execute(
            "INSERT INTO agent_runs(id,mission_id,role,task_id,agent_id,prompt_path,command_json,started_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                "run",
                s.mission(self.conn)["id"],
                "worker",
                self.intake,
                "owner",
                "/prompt",
                "[]",
                s.utcnow(),
            ),
        )
        self.conn.commit()
        with self.assertRaisesRegex(s.SwarmError, "Drain or recover"):
            self.apply()

    def test_concurrent_planners_share_the_same_application(self):
        barrier = threading.Barrier(2)

        def plan():
            conn = s.connect(self.root)
            try:
                barrier.wait(timeout=5)
                return self.apply(conn=conn)
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: plan(), range(2)))
        self.assertEqual({r["replayed"] for r in results}, {True, False})
        self.assertEqual(len({r["applied_policy_application_id"] for r in results}), 1)

    def test_cli_requires_explicit_replacement_reason_and_key(self):
        command = [
            "--root",
            str(self.root),
            "case",
            "apply-policy",
            self.case["id"],
            "pipeline-repair",
            "--var",
            "goal=Restore delivery",
            "--var",
            "test_command=checks",
            "--ready",
            "--replace",
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(s.main(command), 2)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(
                s.main(command + ["--idempotency-key", "cli-plan", "--reason", "Diagnosis ready"]),
                0,
            )
        self.assertFalse(json.loads(output.getvalue())["replayed"])


if __name__ == "__main__":
    unittest.main()
