"""Independent delivery responsibility, race fencing, and provider-driven continuation."""

import concurrent.futures
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import commitments as c, decision_briefs as b, schema
from swarmkit.queries import decision_dict
from swarmkit.prompts import build_prompt

ROOT = Path(__file__).resolve().parents[1]


def brief(options=("CONTINUE", "DEFER")):
    return dict(
        schema_version=1,
        background="The search repair is ready for external review.",
        human_reason="You control publication and merge authority.",
        option_details=[
            dict(
                value=o,
                label=o.title(),
                consequence=(
                    "Publish and conditionally merge"
                    if o == "CONTINUE"
                    else "Leave delivery pending"
                ),
                risk="Review may require changes",
            )
            for o in options
        ],
        recommended_option=options[0] if options else None,
        recommendation_rationale="The scoped checks can bound the change.",
        blocked_outcome="External review and landing.",
        response_required=None if options else "State the permitted scope.",
        evidence=[dict(reference="provider-readback", summary="The current revision is tested.")],
    )


class DeliveryContractsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-delivery-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Land the change", ["Verified landing"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.conn.close)

    def task(self, name="Author", depends=(), required=False):
        return s.add_task(
            self.conn,
            name,
            "Bounded work",
            "implementation",
            ["Verified"],
            list(depends),
            50,
            "manager",
            True,
            delivery_required=required,
        )

    def setup_delivery(self):
        p = self.task(required=True)
        f = self.task("Continue", [p])
        spec = dict(
            producer_task=p,
            followup_task=f,
            title="Land change",
            provider="fixture",
            environment="test",
            terminal_check="change-landed",
            responsible="manager",
            next_check_at=s.future_time(900),
            deadline_at=s.future_time(3600),
            signal_expected=True,
        )
        item = c.create_commitment(self.conn, spec, "manager", "delivery-1")
        return p, f, item

    def produce(self):
        p, f, item = self.setup_delivery()
        s.claim_task(self.conn, p, "author", 600)
        item = c.bind_commitment(
            self.conn, item["id"], p, "author", item["version"], "CL-1", "rev-1", "bind-1"
        )
        s.complete_task(self.conn, p, "author", "Uploaded", ["Tests passed"], [])
        return p, f, item

    def observation(self, item, outcome="pending"):
        return dict(
            provider=item["provider"],
            external_ref=item["external_ref"],
            revision=item["revision"],
            environment=item["environment"],
            check=item["terminal_check"],
            observed_at=s.utcnow(),
            outcome=outcome,
            receipt="provider read-back " + outcome,
        )

    def test_structured_brief_is_atomic_and_exact_options_survive(self):
        t = self.task()
        s.claim_task(self.conn, t, "worker", 600)
        b.configure_briefs(self.conn, "required", "human")
        with self.assertRaises(s.SwarmError):
            s.block_task(self.conn, t, "worker", "human_decision", "Proceed?", None, ["CONTINUE"])
        invalid = brief()
        invalid["option_details"][0]["value"] = "wrong"
        with self.assertRaises(s.SwarmError):
            s.block_task(
                self.conn,
                t,
                "worker",
                "human_decision",
                "Proceed?",
                None,
                ["CONTINUE", "DEFER"],
                invalid,
            )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)
        d = s.block_task(
            self.conn,
            t,
            "worker",
            "human_decision",
            "Release through merge?",
            None,
            ["CONTINUE", "DEFER"],
            brief(),
        )
        data = decision_dict(self.conn, s.decision_row(self.conn, d))
        self.assertEqual(data["brief"], brief())
        board = s.render_board(self.root).read_text()
        report = s.render_status_report(self.root).read_text()
        for text in (board, report):
            self.assertLess(text.index("**Background:**"), text.index("#### Evidence and details"))
            self.assertIn("Publish and conditionally merge", text)
        prompt = build_prompt(self.root, "worker", "next", t)
        self.assertIn("human_reason", prompt)
        s.resolve_decision(self.conn, d, "Proceed within that scope", "human", "CONTINUE")
        self.assertEqual(
            s.require_decision_choice(self.conn, d, "CONTINUE")["selected_option"], "CONTINUE"
        )
        with self.assertRaises(s.SwarmError):
            s.require_decision_choice(self.conn, d, "Continue")

    def test_brief_free_response_cannot_grant_exact_choice(self):
        t = self.task()
        s.claim_task(self.conn, t, "w", 600)
        d = s.block_task(self.conn, t, "w", "human_decision", "What scope?", None, [], brief(()))
        s.resolve_decision(self.conn, d, "Read only", "human")
        with self.assertRaises(s.SwarmError):
            s.require_decision_choice(self.conn, d, "Read only")

    def test_brief_event_failure_rolls_back_blocker(self):
        t = self.task()
        s.claim_task(self.conn, t, "w", 600)
        from swarmkit import tasks

        original = tasks.add_event

        def fail(*args, **kwargs):
            if args[4] == "DECISION_BRIEF_RECORDED":
                raise RuntimeError("disk fault")
            return original(*args, **kwargs)

        with mock.patch.object(tasks, "add_event", side_effect=fail):
            with self.assertRaises(RuntimeError):
                s.block_task(
                    self.conn,
                    t,
                    "w",
                    "human_decision",
                    "Proceed?",
                    None,
                    ["CONTINUE", "DEFER"],
                    brief(),
                )
        self.assertEqual(s.task_row(self.conn, t)["owner"], "w")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 0)

    def test_required_handoff_refuses_missing_unbound_and_cancelled_followup(self):
        p = self.task(required=True)
        s.claim_task(self.conn, p, "w", 600)
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, p, "w", "Uploaded", ["yes"], [])
        # Creation and its event are atomic; failed creation cannot mark a producer required.
        f = self.task("Next", [p])
        spec = dict(
            producer_task=p,
            followup_task=f,
            title="Land",
            provider="fixture",
            environment="test",
            terminal_check="change-landed",
            responsible="manager",
            next_check_at=s.future_time(10),
            deadline_at=s.future_time(600),
            signal_expected=True,
        )
        s.control_mission(self.conn, "pause", "human", "Prepare handoff")
        with mock.patch.object(c, "add_event", side_effect=RuntimeError("fault")):
            with self.assertRaises(RuntimeError):
                c.create_commitment(self.conn, spec, "manager", "create")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM commitments").fetchone()[0], 0)
        s.control_mission(self.conn, "pause", "human", "Plan delivery handoff")
        item = c.create_commitment(self.conn, spec, "manager", "create")
        s.control_mission(self.conn, "resume", "human", "Resume with handoff")
        s.claim_task(self.conn, p, "w-new", 600)
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, p, "w-new", "Uploaded", ["yes"], [])
        c.bind_commitment(self.conn, item["id"], p, "w-new", 1, "CL-1", "rev-1", "bind")
        s.cancel_task(self.conn, f, "manager", "Replace follow-up")
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, p, "w-new", "Uploaded", ["yes"], [])

    def test_cancelled_followup_leaves_obligation_visible_and_blocks_mission(self):
        p, f, item = self.produce()
        s.cancel_task(self.conn, f, "manager", "Need new repair plan")
        self.assertTrue(c.list_commitments(self.conn)[0]["tracking_gap"])
        self.assertIn("TRACKING GAP", s.render_board(self.root).read_text())
        self.assertIn("commitments", s.explain_state(self.conn))
        with self.assertRaisesRegex(s.SwarmError, "commitment"):
            s.complete_mission(self.conn, "All tasks finished", "manager")
        before = self.conn.execute("SELECT COUNT(*) FROM commitment_records").fetchone()[0]
        for _ in range(3):
            s.reconcile_conn(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM commitment_records").fetchone()[0], before
        )

    def test_wait_signal_restart_and_fresh_revision_evidence(self):
        p, f, item = self.produce()
        s.claim_task(self.conn, f, "first", 600)
        item = c.wait_commitment(
            self.conn,
            item["id"],
            f,
            "first",
            item["version"],
            s.future_time(60),
            s.future_time(600),
            True,
            "wait",
        )
        self.assertIsNone(s.task_row(self.conn, f)["owner"])
        c.signal_commitment(
            self.conn,
            item["id"],
            "fixture",
            "review-1",
            "CL-1",
            "Approved with comments",
            "ingress",
        )
        conn = s.connect(self.root)
        try:
            s.claim_task(conn, f, "second", 600)
            with self.assertRaises(s.SwarmError):
                c.observe_commitment(
                    conn,
                    item["id"],
                    f,
                    "first",
                    item["version"],
                    self.observation(item, "satisfied"),
                    "stale",
                )
            item = c.bind_commitment(
                conn, item["id"], f, "second", item["version"], "CL-1", "rev-2", "repair"
            )
            old = self.observation(item, "satisfied")
            old["revision"] = "rev-1"
            with self.assertRaises(s.SwarmError):
                c.observe_commitment(conn, item["id"], f, "second", item["version"], old, "old")
            observed = self.observation(item, "satisfied")
            c.observe_commitment(conn, item["id"], f, "second", item["version"], observed, "landed")
            # Identical retry is harmless, including after the record becomes terminal.
            c.observe_commitment(conn, item["id"], f, "second", item["version"], observed, "landed")
            s.complete_task(conn, f, "second", "Landed", ["Read-back verified"], [])
            s.complete_mission(conn, "Provider confirms landing", "manager")
        finally:
            conn.close()

    def test_signal_between_check_and_wait_cannot_be_lost(self):
        _, f, item = self.produce()
        s.claim_task(self.conn, f, "worker", 600)
        c.observe_commitment(
            self.conn, item["id"], f, "worker", item["version"], self.observation(item), "check"
        )
        c.signal_commitment(
            self.conn, item["id"], "fixture", "review-2", "CL-1", "New comment", "ingress"
        )
        with self.assertRaisesRegex(s.SwarmError, "latest signal"):
            c.wait_commitment(
                self.conn,
                item["id"],
                f,
                "worker",
                item["version"],
                None,
                s.future_time(600),
                True,
                "wait",
            )
        self.assertEqual(s.task_row(self.conn, f)["owner"], "worker")

    def test_provider_outage_can_back_off_after_signal_without_claiming_success(self):
        _, f, item = self.produce()
        s.claim_task(self.conn, f, "worker", 600)
        c.signal_commitment(
            self.conn, item["id"], "fixture", "change", "CL-1", "Inspect", "ingress"
        )
        c.observe_commitment(
            self.conn,
            item["id"],
            f,
            "worker",
            item["version"],
            self.observation(item, "unknown"),
            "provider-unavailable",
        )
        result = c.wait_commitment(
            self.conn,
            item["id"],
            f,
            "worker",
            item["version"],
            s.future_time(60),
            s.future_time(600),
            True,
            "backoff",
        )
        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(s.task_row(self.conn, f)["status"], "WAITING_EXTERNAL")

    def test_concurrent_duplicate_signals_wake_once(self):
        _, f, item = self.produce()
        s.claim_task(self.conn, f, "worker", 600)
        c.wait_commitment(
            self.conn,
            item["id"],
            f,
            "worker",
            item["version"],
            None,
            s.future_time(600),
            True,
            "wait",
        )

        def signal(_):
            conn = s.connect(self.root)
            try:
                c.signal_commitment(
                    conn, item["id"], "fixture", "same", "CL-1", "Review", "ingress"
                )
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(signal, range(4)))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='TASK_WOKEN'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM commitment_records WHERE kind='COMMITMENT_SIGNAL'"
            ).fetchone()[0],
            1,
        )
        with self.assertRaises(s.SwarmError):
            c.signal_commitment(
                self.conn, item["id"], "fixture", "same", "CL-1", "Changed input", "ingress"
            )

    def test_deadline_after_scheduled_check_is_once_and_not_success(self):
        _, _, item = self.produce()
        c.reconcile_commitments(self.conn, at=item["next_check_at"])
        c.reconcile_commitments(self.conn, at=item["deadline_at"])
        c.reconcile_commitments(self.conn, at=item["deadline_at"])
        rows = self.conn.execute(
            "SELECT payload_json FROM commitment_records WHERE kind='COMMITMENT_CHECK_DUE'"
        ).fetchall()
        self.assertEqual(
            [json.loads(r[0])["reason"] for r in rows], ["SCHEDULED_CHECK", "DEADLINE"]
        )
        self.assertEqual(c.row_for(self.conn, item["id"])["status"], "OPEN")

    def test_mission_amendment_requires_explicit_adoption(self):
        _, f, item = self.produce()
        s.control_mission(self.conn, "pause", "human", "Revise scope")
        s.amend_mission(self.conn, "Land safely", ["Verified"], [], "Scope change", "human")
        s.control_mission(self.conn, "resume", "human", "Resume")
        s.approve_task(self.conn, f, "manager")
        s.claim_task(self.conn, f, "new", 600)
        with self.assertRaisesRegex(s.SwarmError, "adoption"):
            c.observe_commitment(
                self.conn,
                item["id"],
                f,
                "new",
                item["version"],
                self.observation(item, "satisfied"),
                "obs",
            )
        s.control_mission(self.conn, "pause", "human", "Adopt")
        item = c.adopt_commitment(
            self.conn, item["id"], f, "manager", item["version"], "Still required", "adopt"
        )
        self.assertFalse(item["adoption_required"])

    def test_policy_graph_and_obligation_publish_together_and_are_idempotent(self):
        s.install_policy(self.conn, ROOT / "examples/policy-packs/author-to-merge", "human")
        s.request_manager_review(self.conn, "plan", "mission", s.mission(self.conn)["id"], "URGENT")
        review = s.claim_manager_review(self.conn, "manager-attempt", 600)
        app = s.apply_policy(
            self.conn,
            "author-to-merge",
            ["goal=repair", "provider=fixture", "environment=test"],
            None,
            "manager-attempt",
            True,
            "plan",
        )
        obligations = c.list_commitments(self.conn)
        self.assertEqual(len(obligations), 1)
        self.assertIsNotNone(obligations[0]["staged_review"])
        self.assertEqual(len(app["tasks"]), 3)
        again = s.apply_policy(
            self.conn,
            "author-to-merge",
            ["goal=repair", "provider=fixture", "environment=test"],
            None,
            "manager-attempt",
            True,
            "plan",
        )
        self.assertEqual(again["id"], app["id"])
        s.finish_manager_review(self.conn, review["id"], "manager-attempt", True)
        self.assertIsNone(c.list_commitments(self.conn)[0]["staged_review"])

    def test_schema_13_migration_rolls_back_new_tables(self):
        self.conn.execute("DROP TABLE commitment_records")
        self.conn.execute("DROP TABLE commitments")
        self.conn.execute("DROP TABLE required_handoffs")
        self.conn.execute("DROP TABLE decision_briefs")
        self.conn.execute("UPDATE meta SET value='13' WHERE key='schema_version'")
        self.conn.commit()
        original = schema.execute_schema

        def fail(conn, sql):
            original(conn, sql)
            raise RuntimeError("after DDL")

        with mock.patch.object(schema, "execute_schema", side_effect=fail):
            with self.assertRaises(RuntimeError):
                schema.ensure_schema(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            "13",
        )
        self.assertIsNone(
            self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='commitments'").fetchone()
        )
        schema.ensure_schema(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            s.SCHEMA_VERSION,
        )

    def test_process_crash_rolls_back_handoff_but_preserves_committed_signal(self):
        _, _, item = self.produce()
        code = """import os,sys
from pathlib import Path
import swarmctl as s
from swarmkit import commitments as c
conn=s.connect(Path(sys.argv[1]))
c.signal_commitment(conn,sys.argv[2],"fixture","durable","CL-1","Review","ingress")
with s.transaction(conn):
 conn.execute("UPDATE commitments SET status='SATISFIED'")
 os._exit(71)
"""
        proc = subprocess.run(
            [sys.executable, "-B", "-c", code, str(self.root), item["id"]], cwd=ROOT
        )
        self.assertEqual(proc.returncode, 71)
        self.assertEqual(c.row_for(self.conn, item["id"])["status"], "OPEN")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM commitment_records WHERE kind='COMMITMENT_SIGNAL'"
            ).fetchone()[0],
            1,
        )

    def test_provider_assessment_never_treats_approval_as_comment_resolution_or_landing(self):
        spec = importlib.util.spec_from_file_location(
            "change_check", ROOT / "examples/check_change.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observation = dict(
            provider="fixture",
            external_ref="CL-1",
            revision="rev-1",
            environment="test",
            observed_at=s.utcnow(),
            receipt="readback",
            review_approved=True,
            comments_addressed=False,
            ci_passed=True,
            mergeable=True,
            landed=False,
            closed=False,
        )
        result = module.assess(observation)
        self.assertEqual(result["next_action"], "address-comments")
        self.assertFalse(result["authorizes_merge"])
        observation["comments_addressed"] = True
        self.assertEqual(module.assess(observation)["observation"]["outcome"], "pending")
        observation["closed"] = True
        self.assertEqual(module.assess(observation)["observation"]["outcome"], "rejected")
        observation["landed"] = True
        self.assertEqual(module.assess(observation)["observation"]["outcome"], "satisfied")

    def test_complete_author_gate_repair_merge_with_lost_provider_response(self):
        from swarmkit import grants

        s.install_policy(self.conn, ROOT / "examples/policy-packs/author-to-merge", "human")
        app = s.apply_policy(
            self.conn,
            "author-to-merge",
            ["goal=repair", "provider=fixture", "environment=test"],
            None,
            "manager",
            True,
            "workflow",
        )
        task_ids = {t["stage_id"]: t["task_id"] for t in app["tasks"]}
        p, g, f = (task_ids[k] for k in ("author", "release", "continue"))
        item = c.list_commitments(self.conn)[0]
        s.claim_task(self.conn, p, "author", 600)
        item = c.bind_commitment(
            self.conn, item["id"], p, "author", 1, "CL-1", "rev-1", "created-pr"
        )
        s.complete_task(self.conn, p, "author", "PR uploaded", ["Tests passed"], [])
        s.claim_task(self.conn, g, "gate-first", 600)
        decision = s.block_task(
            self.conn,
            g,
            "gate-first",
            "human_decision",
            "Release through conditional merge?",
            None,
            ["CONTINUE", "DEFER"],
            brief(),
        )
        s.link_decision(self.conn, decision, f, "manager")
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, f, "too-early", 600)
        s.resolve_decision(
            self.conn,
            decision,
            "Address all feedback, repair CI, merge when approved and ready",
            "human",
            "CONTINUE",
        )
        s.claim_task(self.conn, g, "gate-second", 600)
        s.acknowledge_decision(self.conn, decision, g, "gate-second")
        s.complete_task(
            self.conn, g, "gate-second", "Released", ["Exact continuation approved"], []
        )
        s.claim_task(self.conn, f, "delivery-first", 600)
        s.acknowledge_decision(self.conn, decision, f, "delivery-first")
        item = c.wait_commitment(
            self.conn,
            item["id"],
            f,
            "delivery-first",
            item["version"],
            s.future_time(60),
            s.future_time(600),
            True,
            "request-review-wait",
        )
        # The ingress adapter runs in another process; core survives agent context loss.
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "swarmctl.py"),
                "--root",
                str(self.root),
                "commitment",
                "signal",
                item["id"],
                "--source",
                "fixture",
                "--external-id",
                "review-approved-with-comments",
                "--external-ref",
                "CL-1",
                "--note",
                "Approval with comments",
                "--actor",
                "ingress",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        s.claim_task(self.conn, f, "delivery-second", 600)
        s.acknowledge_decision(self.conn, decision, f, "delivery-second")
        item = c.bind_commitment(
            self.conn,
            item["id"],
            f,
            "delivery-second",
            item["version"],
            "CL-1",
            "rev-2",
            "address-comments-and-ci",
        )
        c.observe_commitment(
            self.conn,
            item["id"],
            f,
            "delivery-second",
            item["version"],
            self.observation(item),
            "fresh-pending",
        )
        with self.assertRaisesRegex(s.SwarmError, "satisfied delivery"):
            s.complete_task(self.conn, f, "delivery-second", "Green", ["Approval and CI"], [])
        conditions = [
            dict(id=name, check=name, waivable=False, max_age_seconds=60)
            for name in ("review-valid", "comments-addressed", "required-ci", "mergeable")
        ]
        grant = grants.issue_grant(
            self.conn,
            decision,
            "CONTINUE",
            dict(
                provider="fixture",
                action="merge",
                resources=["CL-1"],
                revision="rev-2",
                environment="test",
                delegate="issuer",
                expires_at=s.future_time(300),
                conditions=conditions,
            ),
            "trusted-issuer",
        )
        for condition in conditions:
            path = Path(self.temp.name) / (condition["id"] + ".json")
            path.write_text(json.dumps({"revision": "rev-2", "passed": True}))
            grants.record_condition(
                self.conn,
                grant,
                f,
                "delivery-second",
                condition["id"],
                condition["check"],
                "rev-2",
                "test",
                0,
                str(path),
                s.utcnow(),
                s.future_time(60),
            )
        effect = s.prepare_effect(
            self.conn,
            f,
            "delivery-second",
            "merge-CL-1-rev-2",
            "CL-1",
            "rev-2",
            {},
            grant,
            "fixture",
            "merge",
            "test",
        )
        s.transition_effect(self.conn, effect["id"], "start", "delivery-second")
        provider = Path(self.temp.name) / "provider.json"
        provider.write_text(json.dumps({"revision": "rev-2", "merged": False, "merge_count": 0}))
        code = """import json,os,sys
from pathlib import Path
p=Path(sys.argv[1]);v=json.loads(p.read_text());v.update(merged=True,merge_count=v["merge_count"]+1);p.write_text(json.dumps(v));os._exit(72)
"""
        proc = subprocess.run([sys.executable, "-B", "-c", code, str(provider)])
        self.assertEqual(proc.returncode, 72)
        with self.assertRaises(s.SwarmError):
            c.observe_commitment(
                self.conn,
                item["id"],
                f,
                "delivery-second",
                item["version"],
                self.observation(item, "satisfied"),
                "premature",
            )
        with self.assertRaises(s.SwarmError):
            s.transition_effect(self.conn, effect["id"], "start", "delivery-second")
        self.assertTrue(json.loads(provider.read_text())["merged"])
        s.transition_effect(
            self.conn,
            effect["id"],
            "succeeded",
            "trusted-adapter",
            "provider read-back CL-1 rev-2 landed",
        )
        c.observe_commitment(
            self.conn,
            item["id"],
            f,
            "delivery-second",
            item["version"],
            self.observation(item, "satisfied"),
            "landed",
        )
        s.complete_task(
            self.conn,
            f,
            "delivery-second",
            "Landed",
            ["All feedback handled; provider confirms rev-2"],
            [],
        )
        s.complete_mission(self.conn, "Provider verified landing", "manager")
        self.assertEqual(json.loads(provider.read_text())["merge_count"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 1)

    def test_case_stays_open_with_no_live_tasks_and_scope_cannot_drift(self):
        case = s.open_case(
            self.root,
            self.conn,
            "fixture",
            "case-1",
            "Repair",
            "Land",
            50,
            "ingress",
            ["Verified"],
            ready=True,
        )
        intake = case["tasks"][0]["id"]
        p = self.task("Produce")
        f = self.task("Deliver", [p])
        s.link_case_task(self.conn, case["id"], p, "manager")
        s.link_case_task(self.conn, case["id"], f, "manager")
        spec = dict(
            producer_task=p,
            followup_task=f,
            title="Land",
            provider="fixture",
            environment="test",
            terminal_check="change-landed",
            responsible="manager",
            next_check_at=s.future_time(60),
            deadline_at=s.future_time(600),
            signal_expected=True,
        )
        item = c.create_commitment(self.conn, spec, "manager", "case-delivery")
        s.claim_task(self.conn, p, "author", 600)
        c.bind_commitment(self.conn, item["id"], p, "author", 1, "CL-1", "rev-1", "bind")
        s.complete_task(self.conn, p, "author", "Uploaded", ["yes"], [])
        s.cancel_task(self.conn, intake, "manager", "Intake superseded")
        s.cancel_task(self.conn, f, "manager", "Replan")
        self.assertEqual(s.case_row(self.conn, case["id"])["status"], "WAITING_EXTERNAL")
        self.assertEqual(s.mission_snapshot(self.conn)["cases"][0]["open_commitment_count"], 1)
        other = s.add_workstream(self.conn, "Other", "Other outcome", "manager")
        with self.assertRaises(s.SwarmError):
            s.link_task_workstream(self.conn, other, p, "manager")
        s.cancel_case(self.conn, case["id"], "human", "Stop delivery")
        self.assertEqual(c.row_for(self.conn, item["id"])["status"], "CANCELLED")

    def test_late_signal_and_pause_do_not_grant_execution(self):
        _, f, item = self.produce()
        s.claim_task(self.conn, f, "w", 600)
        item = c.wait_commitment(
            self.conn, item["id"], f, "w", item["version"], None, s.future_time(600), True, "wait"
        )
        s.control_mission(self.conn, "pause", "human", "Hold")
        c.signal_commitment(self.conn, item["id"], "fixture", "signal", "CL-1", "Ready", "ingress")
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, f, "paused", 600)
        c.cancel_commitment(self.conn, item["id"], "manager", item["version"], "Withdraw")
        c.signal_commitment(self.conn, item["id"], "fixture", "late", "CL-1", "Merged?", "ingress")
        self.assertEqual(c.row_for(self.conn, item["id"])["status"], "CANCELLED")

    def test_failed_review_keeps_commitment_unpublished(self):
        s.request_manager_review(self.conn, "plan", "mission", s.mission(self.conn)["id"], "URGENT")
        review = s.claim_manager_review(self.conn, "manager-attempt", 600)
        _, _, item = self.setup_delivery()
        s.finish_manager_review(self.conn, review["id"], "manager-attempt", False, "Interrupted")
        self.assertEqual(c.row_for(self.conn, item["id"])["staged_review"], review["id"])
        with self.assertRaises(s.SwarmError):
            c.create_commitment(self.conn, item["specification"], "manager-attempt", "another")
        c.reconcile_commitments(self.conn, at=item["deadline_at"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM commitment_records WHERE kind='COMMITMENT_CHECK_DUE'"
            ).fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
