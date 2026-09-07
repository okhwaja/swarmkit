import json
import concurrent.futures
import contextlib
import datetime as dt
import io
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from swarmkit import runtime
import zipfile


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

import swarmctl  # noqa: E402


class SwarmLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarmctl-test-")
        self.base = Path(self.temp.name)
        self.root = self.base / ".swarm"
        self.mission_id = swarmctl.initialize(
            self.root,
            "Restore the test pipeline",
            ["New data arrives", "Backlog is accounted for"],
            ["No destructive action without approval"],
        )

    def tearDown(self):
        self.temp.cleanup()

    def connection(self):
        return swarmctl.connect(self.root)

    def test_dependency_decision_ack_and_completion(self):
        conn = self.connection()
        try:
            first = swarmctl.add_task(
                conn, "Trace failure", "Find the failing stage", "discovery",
                ["Failing boundary is supported by logs"], [], 80, "manager", True,
            )
            second = swarmctl.add_task(
                conn, "Repair pipeline", "Repair the supported cause", "implementation",
                ["Live record reaches destination"], [first], 70, "manager", True,
            )
            self.assertEqual(swarmctl.task_row(conn, first)["status"], "READY")
            self.assertEqual(swarmctl.task_row(conn, second)["status"], "PROPOSED")

            swarmctl.claim_task(conn, first, "worker-a", 1800)
            swarmctl.checkpoint_task(conn, first, "worker-a", "Found failing boundary", "Verify logs", 1800)
            evidence = self.base / "trace.txt"
            evidence.write_text("queue healthy; destination rejected credential\n", encoding="utf-8")
            swarmctl.complete_task(
                conn, first, "worker-a", "Expired destination credential isolated",
                ["Compared first failure with credential rotation"], [str(evidence)],
            )
            self.assertEqual(swarmctl.task_row(conn, second)["status"], "READY")

            swarmctl.claim_task(conn, second, "worker-b", 1800)
            decision = swarmctl.block_task(
                conn, second, "worker-b", "human_decision",
                "May ingestion pause during repair?", "Pause for the controlled window",
                ["Pause", "Continue"],
            )
            version = swarmctl.resolve_decision(conn, decision, "Pause", "human", "Pause")
            self.assertEqual(swarmctl.decision_dict(conn, swarmctl.decision_row(conn, decision))["selected_option"], "Pause")
            authorization = swarmctl.require_decision_choice(conn, decision, "Pause")
            self.assertTrue(authorization["authorized"])
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.require_decision_choice(conn, decision, "Continue")
            self.assertEqual(swarmctl.task_row(conn, second)["status"], "READY")
            swarmctl.claim_task(conn, second, "worker-c", 1800)
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.checkpoint_task(conn, second, "worker-c", "Starting", "Repair", 1800)
            swarmctl.acknowledge_decision(conn, decision, second, "worker-c")
            ack = conn.execute(
                "SELECT version FROM decision_acks WHERE decision_id=? AND task_id=?",
                (decision, second),
            ).fetchone()
            self.assertEqual(ack["version"], version)
            swarmctl.checkpoint_task(conn, second, "worker-c", "Decision incorporated", "Repair", 1800)
            revised = swarmctl.revise_decision(
                conn, decision, "Pause, but limit the window to ten minutes", "human", "Pause"
            )
            self.assertGreater(revised, version)
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.revise_decision(conn, decision, "Invalid choice", "human", "Unknown")
            self.assertEqual(swarmctl.task_row(conn, second)["status"], "READY")
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.complete_task(
                    conn, second, "worker-c", "Stale completion",
                    ["This should be fenced"], [],
                )
            swarmctl.claim_task(conn, second, "worker-d", 1800)
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.checkpoint_task(conn, second, "worker-d", "Starting", "Repair", 1800)
            swarmctl.acknowledge_decision(conn, decision, second, "worker-d")
            swarmctl.checkpoint_task(conn, second, "worker-d", "Revised decision incorporated", "Repair", 1800)
            swarmctl.complete_task(
                conn, second, "worker-d", "Pipeline repaired",
                ["Representative record reached destination"], [],
            )
            swarmctl.complete_mission(conn, "Both success conditions verified", "manager")
            self.assertEqual(swarmctl.mission(conn)["status"], "DONE")
            self.assertTrue(swarmctl.doctor(conn)["ok"])
        finally:
            conn.close()

    def test_expired_lease_is_requeued_and_old_owner_is_fenced(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(
                conn, "Inspect queue", "Read queue state", "discovery",
                ["Queue depth recorded"], [], 50, "manager", True,
            )
            swarmctl.claim_task(conn, task, "worker-old", 30)
            conn.execute("UPDATE tasks SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", task))
            conn.commit()
            changed = swarmctl.reconcile_conn(conn)
            self.assertIn((task, "READY"), changed)
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.checkpoint_task(conn, task, "worker-old", "late update", "continue", 1800)
            generation = swarmctl.claim_task(conn, task, "worker-new", 1800)
            self.assertEqual(generation, 2)
            fact = swarmctl.record_fact(
                conn, "queue-health", "healthy", "queue probe", "worker-new", task,
                observed_at="2020-01-01T00:00:00Z", ttl_seconds=60,
            )
            swarmctl.reconcile_conn(conn)
            status = conn.execute("SELECT status FROM facts WHERE id=?", (fact,)).fetchone()["status"]
            self.assertEqual(status, "EXPIRED")
        finally:
            conn.close()

    def test_inbox_cursor_prompt_and_audit_export(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(
                conn, "Inspect logs", "Build a failure timeline", "discovery",
                ["Timeline cites timestamps"], [], 50, "manager", True,
            )
            unseen = swarmctl.inbox(conn, "worker-1", advance=True)
            self.assertGreaterEqual(len(unseen), 2)
            self.assertEqual(swarmctl.inbox(conn, "worker-1"), [])
        finally:
            conn.close()

        prompt = swarmctl.build_prompt(self.root, "worker", "worker-1", task)
        self.assertIn(str(self.root), prompt)
        self.assertIn(task, prompt)
        self.assertNotIn("<command_prefix>", prompt)
        self.assertNotIn("<agent_id>", prompt)
        self.assertNotIn("<task_id>", prompt)

        export_path = self.base / "audit.zip"
        swarmctl.export_audit(self.root, export_path, include_artifacts=True)
        self.assertTrue(export_path.exists())
        with zipfile.ZipFile(str(export_path)) as archive:
            names = set(archive.namelist())
            self.assertIn("swarm-audit/events.jsonl", names)
            self.assertIn("swarm-audit/snapshot.json", names)
            self.assertIn("swarm-audit/cases.json", names)
            self.assertIn("swarm-audit/state.sqlite3", names)
            self.assertIn("swarm-audit/REVIEW_ME.md", names)
            snapshot = json.loads(archive.read("swarm-audit/snapshot.json"))
            self.assertEqual(snapshot["mission"]["id"], self.mission_id)
            manifest = json.loads(archive.read("swarm-audit/manifest.json"))
            inventoried = {item["path"] for item in manifest["files"]}
            self.assertIn("state.sqlite3", inventoried)

    def test_runner_dry_run_substitutes_without_shell(self):
        config_path = self.root / "runner.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["command"] = ["third-party-harness", "run", "--prompt", "{prompt_file}", "--role", "{role}"]
        config_path.write_text(json.dumps(config), encoding="utf-8")
        result = swarmctl.dispatch(self.root, "manager", "manager", dry_run=True)
        self.assertEqual(result["command"][0], "third-party-harness")
        self.assertEqual(result["command"][-1], "manager")
        self.assertTrue(Path(result["prompt_path"]).exists())

    def test_decision_can_be_linked_to_multiple_tasks(self):
        conn = self.connection()
        try:
            stream = swarmctl.add_workstream(
                conn, "Controlled repair", "Repair and replay safely", "manager", "ACTIVE"
            )
            first = swarmctl.add_task(
                conn, "Repair", "Perform controlled repair", "implementation",
                ["Repair verified"], [], 60, "manager", True, stream,
            )
            second = swarmctl.add_task(
                conn, "Replay", "Replay the backlog", "implementation",
                ["Backlog verified"], [], 50, "manager", True, stream,
            )
            swarmctl.claim_task(conn, first, "worker-a", 1800)
            decision = swarmctl.block_task(
                conn, first, "worker-a", "human_decision", "May delivery pause?",
                "Pause", ["Pause", "Continue"],
            )
            self.assertTrue(swarmctl.link_decision(conn, decision, second, "manager"))
            self.assertEqual(swarmctl.task_row(conn, second)["status"], "BLOCKED")
            workstream = swarmctl.workstream_dict(conn, swarmctl.workstream_row(conn, stream))
            self.assertEqual([item["id"] for item in workstream["needs_human"]], [decision])
            swarmctl.resolve_decision(conn, decision, "Pause", "human")
            self.assertEqual(swarmctl.task_row(conn, first)["status"], "READY")
            self.assertEqual(swarmctl.task_row(conn, second)["status"], "READY")
        finally:
            conn.close()

    def test_agent_exit_without_completion_requeues_task(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(
                conn, "Read destination", "Inspect destination state", "discovery",
                ["State is recorded"], [], 50, "manager", True,
            )
            swarmctl.claim_task(conn, task, "worker-short", 1800)
        finally:
            conn.close()
        config_path = self.root / "runner.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["command"] = [sys.executable, "-c", "print('agent exited without update')", "{prompt_file}"]
        config_path.write_text(json.dumps(config), encoding="utf-8")
        result = swarmctl.dispatch(self.root, "worker", "worker-short", task_id=task)
        self.assertEqual(result["exit_code"], 0)
        conn = self.connection()
        try:
            self.assertEqual(swarmctl.task_row(conn, task)["status"], "READY")
            event = conn.execute(
                "SELECT 1 FROM events WHERE entity_id=? AND event_type='TASK_RUN_ENDED_INCOMPLETE'", (task,)
            ).fetchone()
            self.assertIsNotNone(event)
        finally:
            conn.close()

    def test_task_claim_is_atomic_across_connections(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(
                conn, "Atomic claim", "Only one agent may own this", "discovery",
                ["Exactly one claim succeeds"], [], 50, "manager", True,
            )
        finally:
            conn.close()

        def attempt(agent):
            local = self.connection()
            try:
                return (agent, swarmctl.claim_task(local, task, agent, 1800), None)
            except swarmctl.SwarmError as exc:
                return (agent, None, str(exc))
            finally:
                local.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ["worker-one", "worker-two"]))
        successes = [outcome for outcome in outcomes if outcome[1] is not None]
        failures = [outcome for outcome in outcomes if outcome[2] is not None]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)

    def test_workstream_drives_executive_report_and_completion_gate(self):
        conn = self.connection()
        try:
            stream = swarmctl.add_workstream(
                conn, "Restore delivery", "Restore correct live delivery", "manager", "ACTIVE"
            )
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.update_workstream(
                    conn, stream, "manager", forecast_latest="2030-01-01T00:00:00Z"
                )
            swarmctl.update_workstream(
                conn, stream, "manager", summary="Failure isolated; repair remains",
                forecast_earliest="2030-01-01T00:00:00Z",
                forecast_latest="2030-01-01T02:00:00Z",
                forecast_confidence="medium", forecast_basis="One repair and one validation remain",
            )
            active_stream = swarmctl.workstream_dict(conn, swarmctl.workstream_row(conn, stream))
            self.assertIn(
                "2030-01-01T00:00:00Z to 2030-01-01T02:00:00Z",
                swarmctl.forecast_text(active_stream),
            )
            task = swarmctl.add_task(
                conn, "Repair", "Repair the failure", "implementation",
                ["Live record arrives"], [], 60, "manager", True, stream,
            )
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.update_workstream(conn, stream, "manager", status="DONE")
            swarmctl.claim_task(conn, task, "worker", 1800)
            swarmctl.complete_task(
                conn, task, "worker", "Delivery restored", ["Live record arrived"], []
            )
            swarmctl.update_workstream(
                conn, stream, "manager", status="DONE", summary="Live delivery verified"
            )
            swarmctl.complete_mission(conn, "Mission and workstream outcomes verified", "manager")
            task_data = swarmctl.task_dict(conn, swarmctl.task_row(conn, task))
            self.assertEqual(task_data["workstream_id"], stream)
        finally:
            conn.close()
        status_path = swarmctl.render_status_report(self.root)
        report = status_path.read_text(encoding="utf-8")
        self.assertIn("Restore delivery", report)
        self.assertIn("Expected timing: Completed", report)
        self.assertIn("Needs anything from you: No", report)

    def test_existing_workspace_is_upgraded_automatically(self):
        conn = self.connection()
        try:
            conn.execute("DROP TABLE task_workstreams")
            conn.execute("DROP TABLE workstreams")
            conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
            conn.commit()
        finally:
            conn.close()
        upgraded = self.connection()
        try:
            version = upgraded.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
            table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workstreams'"
            ).fetchone()
            policy_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='policy_applications'"
            ).fetchone()
            extension_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='extensions'"
            ).fetchone()
            delivery_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='deliveries'"
            ).fetchone()
            case_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cases'"
            ).fetchone()
            finding_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='findings'"
            ).fetchone()
            wait_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='external_waits'"
            ).fetchone()
            review_table = upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='manager_reviews'"
            ).fetchone()
            self.assertEqual(version, swarmctl.SCHEMA_VERSION)
            self.assertIsNotNone(table)
            self.assertIsNotNone(policy_table)
            self.assertIsNotNone(extension_table)
            self.assertIsNotNone(delivery_table)
            self.assertIsNotNone(case_table)
            self.assertIsNotNone(finding_table)
            self.assertIsNotNone(wait_table)
            self.assertIsNotNone(review_table)
            self.assertEqual(swarmctl.mission_mode(upgraded), "FINITE")
        finally:
            upgraded.close()

    def test_human_ask_creates_linked_briefing(self):
        conn = self.connection()
        try:
            stream = swarmctl.add_workstream(
                conn, "Recover backlog", "Recover all valid records", "manager", "ACTIVE"
            )
        finally:
            conn.close()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = swarmctl.main([
                "--root", str(self.root), "ask",
                "--workstream", stream,
                "--question", "Why does replay require deduplication?",
            ])
        self.assertEqual(exit_code, 0)
        inquiry_id = json.loads(output.getvalue())["inquiry_task_id"]
        conn = self.connection()
        try:
            inquiry = swarmctl.task_dict(conn, swarmctl.task_row(conn, inquiry_id))
            self.assertEqual(inquiry["kind"], "briefing")
            self.assertEqual(inquiry["workstream_id"], stream)
            self.assertEqual(inquiry["status"], "READY")
        finally:
            conn.close()

    def test_policy_pack_creates_enforced_fresh_review_workflow(self):
        policy_source = PACKAGE_ROOT / "examples" / "policy-packs" / "pr-adversarial-review"
        review_artifact = self.base / "review.md"
        review_artifact.write_text("No material findings\n", encoding="utf-8")
        conn = self.connection()
        try:
            installed = swarmctl.install_policy(conn, policy_source, "human")
            self.assertEqual(installed["id"], "pr-adversarial-review")
            stream = swarmctl.add_workstream(
                conn, "Ship repair", "Deliver a reviewed pull request", "manager", "ACTIVE"
            )
            application = swarmctl.apply_policy(
                conn, "pr-adversarial-review",
                ["goal=repair queue handling", "test_command=python3 -m unittest"],
                stream, "manager", True,
            )
            self.assertEqual(len(application["tasks"]), 5)
            stage_tasks = {item["stage_id"]: item["task_id"] for item in application["tasks"]}
            self.assertEqual(swarmctl.task_row(conn, stage_tasks["implement-and-open-pr"])["status"], "READY")
            self.assertEqual(swarmctl.task_row(conn, stage_tasks["adversarial-review-1"])["status"], "PROPOSED")

            first = stage_tasks["implement-and-open-pr"]
            swarmctl.claim_task(conn, first, "implementer", 1800)
            swarmctl.complete_task(conn, first, "implementer", "PR opened", ["Tests passed"], [])

            review_one = stage_tasks["adversarial-review-1"]
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.claim_task(conn, review_one, "implementer", 1800)
            swarmctl.claim_task(conn, review_one, "reviewer-one", 1800)
            prompt = swarmctl.build_prompt(self.root, "verifier", "reviewer-one", review_one)
            self.assertIn("adversarial-review", prompt)
            self.assertIn("untrusted data", prompt)
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.complete_task(
                    conn, review_one, "reviewer-one", "Review claimed without evidence",
                    ["adversarial-review completed against commit SHA abc123"], [],
                )
            swarmctl.complete_task(
                conn, review_one, "reviewer-one", "Review recorded",
                ["adversarial-review completed against commit SHA abc123"], [str(review_artifact)],
            )

            remediation = stage_tasks["remediate-review-1"]
            swarmctl.claim_task(conn, remediation, "remediator", 1800)
            swarmctl.complete_task(conn, remediation, "remediator", "Findings fixed", ["Tests passed"], [])

            review_two = stage_tasks["adversarial-review-2"]
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.claim_task(conn, review_two, "reviewer-one", 1800)
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.claim_task(conn, review_two, "remediator", 1800)
            swarmctl.claim_task(conn, review_two, "reviewer-two", 1800)
            swarmctl.complete_task(
                conn, review_two, "reviewer-two", "Fresh review recorded",
                ["Independent adversarial-review completed against commit SHA def456"], [str(review_artifact)],
            )

            final = stage_tasks["finalize-pr"]
            swarmctl.claim_task(conn, final, "finalizer", 1800)
            swarmctl.complete_task(conn, final, "finalizer", "PR is green", ["Final tests passed"], [])
            finished = swarmctl.policy_application_dict(conn, application["id"])
            self.assertEqual(finished["status"], "DONE")
        finally:
            conn.close()

    def test_policy_manifest_rejects_forward_dependency(self):
        manifest = {
            "schema_version": 1,
            "id": "bad-policy",
            "version": "1",
            "name": "Bad",
            "description": "Invalid ordering",
            "when_to_use": "Never",
            "stages": [{
                "id": "first", "title": "First", "description": "Bad dependency",
                "kind": "implementation", "acceptance": ["Done"],
                "depends_on": ["later"],
            }],
        }
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.validate_policy_manifest(manifest)

    def test_delivery_outbox_is_idempotent_allowlisted_and_acknowledged(self):
        extension_source = PACKAGE_ROOT / "examples" / "extensions" / "harness-email"
        content = self.base / "status.md"
        content.write_text("# Status\n\nPipeline is recovering.\n", encoding="utf-8")
        conn = self.connection()
        try:
            installed = swarmctl.install_extension(conn, extension_source, "human")
            self.assertEqual(installed["id"], "harness-email-example")
            manager_prompt = swarmctl.build_prompt(self.root, "manager", "manager")
            self.assertIn("harness-email-example", manager_prompt)
            queued = swarmctl.enqueue_delivery(
                self.root, conn, "harness-email-example", "email", "Pipeline status",
                ["replace-me@example.com"], content, ["window=hour-22"],
                "status-hour-22", "scheduler",
            )
            self.assertTrue(queued["created"])
            duplicate = swarmctl.enqueue_delivery(
                self.root, conn, "harness-email-example", "email", "Pipeline status",
                ["replace-me@example.com"], content, ["window=hour-22"],
                "status-hour-22", "scheduler",
            )
            self.assertFalse(duplicate["created"])
            self.assertEqual(duplicate["id"], queued["id"])
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.enqueue_delivery(
                    self.root, conn, "harness-email-example", "email", "Different",
                    ["replace-me@example.com"], content, [], "status-hour-22", "scheduler",
                )
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.enqueue_delivery(
                    self.root, conn, "harness-email-example", "email", "Pipeline status",
                    ["outside@example.net"], content, [], "outside", "scheduler",
                )
            claimed = swarmctl.claim_delivery(conn, queued["id"], "emailer-one", 600)
            self.assertEqual(claimed["status"], "CLAIMED")
            swarmctl.mark_delivery_failed(conn, queued["id"], "emailer-one", "provider unavailable")
            swarmctl.retry_delivery(conn, queued["id"], "operator")
            swarmctl.claim_delivery(conn, queued["id"], "emailer-two", 600)
            swarmctl.mark_delivery_sent(conn, queued["id"], "emailer-two", "provider-message-123")
            final = swarmctl.delivery_dict(
                conn, conn.execute("SELECT * FROM deliveries WHERE id=?", (queued["id"],)).fetchone()
            )
            self.assertEqual(final["status"], "SENT")
            self.assertEqual(final["attempt_count"], 2)
            self.assertEqual(final["provider_receipt"], "provider-message-123")
            self.assertTrue(final["content_intact"])
            lease_job = swarmctl.enqueue_delivery(
                self.root, conn, "harness-email-example", "email", "Lease test",
                ["replace-me@example.com"], content, [], "lease-test", "test",
            )
            swarmctl.claim_delivery(conn, lease_job["id"], "lost-emailer", 30)
            conn.execute("UPDATE deliveries SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00Z", lease_job["id"]))
            conn.commit()
            self.assertIn((lease_job["id"], "UNKNOWN"), swarmctl.reconcile_conn(conn))
            self.assertTrue(swarmctl.doctor(conn)["ok"])
        finally:
            conn.close()
        audit_path = self.base / "delivery-audit.zip"
        swarmctl.export_audit(self.root, audit_path)
        with zipfile.ZipFile(str(audit_path)) as archive:
            names = set(archive.namelist())
            self.assertTrue(any(name.startswith("swarm-audit/outbox/%s/" % queued["id"]) for name in names))
            snapshot = json.loads(archive.read("swarm-audit/snapshot.json"))
            self.assertEqual(snapshot["deliveries"][0]["provider_receipt"], "provider-message-123")

    def test_command_delivery_extension_requires_durable_ack(self):
        extension_dir = self.base / "command-extension"
        extension_dir.mkdir()
        adapter_code = (
            "import json,subprocess,sys; e=json.load(open(sys.argv[1])); "
            "subprocess.run([sys.executable,sys.argv[2],'--root',sys.argv[3],"
            "'delivery','sent',e['delivery_id'],'--agent',sys.argv[4],"
            "'--receipt','provider-test-receipt'],check=True)"
        )
        manifest = {
            "schema_version": 1,
            "id": "test-command-email",
            "version": "1.0.0",
            "name": "Test command email",
            "kind": "delivery",
            "description": "Test-only provider adapter",
            "handles": ["email"],
            "guidance": "GUIDANCE.md",
            "executor": {
                "type": "command",
                "command": [
                    sys.executable, "-c", adapter_code, "{envelope_file}",
                    str(PACKAGE_ROOT / "swarmctl.py"), "{root}", "{agent_id}",
                ],
            },
            "recipient_policy": {
                "allowed_recipients": ["test@example.com"],
                "allowed_domains": [],
            },
        }
        (extension_dir / "extension.json").write_text(json.dumps(manifest), encoding="utf-8")
        (extension_dir / "GUIDANCE.md").write_text("Use the test adapter.\n", encoding="utf-8")
        content = self.base / "message.txt"
        content.write_text("test message\n", encoding="utf-8")
        conn = self.connection()
        try:
            swarmctl.install_extension(conn, extension_dir, "test")
            queued = swarmctl.enqueue_delivery(
                self.root, conn, "test-command-email", "email", "Test",
                ["test@example.com"], content, [], "command-test-1", "test",
            )
        finally:
            conn.close()
        dry_run = swarmctl.dispatch_delivery(self.root, queued["id"], "command-emailer", True)
        self.assertEqual(dry_run["executor_type"], "command")
        self.assertTrue(Path(dry_run["envelope_path"]).is_file())
        result = swarmctl.dispatch_delivery(self.root, queued["id"], "command-emailer")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["delivery_status"], "SENT")
        conn = self.connection()
        try:
            row = conn.execute("SELECT * FROM deliveries WHERE id=?", (queued["id"],)).fetchone()
            self.assertEqual(row["provider_receipt"], "provider-test-receipt")
        finally:
            conn.close()

        manifest["id"] = "test-unacknowledged-email"
        manifest["executor"]["command"] = [
            sys.executable, "-c", "print('no provider receipt')", "{envelope_file}",
        ]
        (extension_dir / "extension.json").write_text(json.dumps(manifest), encoding="utf-8")
        conn = self.connection()
        try:
            swarmctl.install_extension(conn, extension_dir, "test")
            unacknowledged = swarmctl.enqueue_delivery(
                self.root, conn, "test-unacknowledged-email", "email", "Unacknowledged",
                ["test@example.com"], content, [], "command-test-unack", "test",
            )
        finally:
            conn.close()
        result = swarmctl.dispatch_delivery(self.root, unacknowledged["id"], "unack-emailer")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["delivery_status"], "UNKNOWN")
        conn = self.connection()
        try:
            row = conn.execute(
                "SELECT * FROM deliveries WHERE id=?", (unacknowledged["id"],)
            ).fetchone()
            self.assertIn("without recording provider acknowledgment", row["last_error"])
        finally:
            conn.close()

    def test_delivery_extension_manifest_rejects_shell_and_open_recipients(self):
        base = {
            "schema_version": 1, "id": "bad-extension", "version": "1",
            "name": "Bad", "kind": "delivery", "description": "Invalid",
            "handles": ["email"], "guidance": "GUIDANCE.md",
            "executor": {"type": "command", "command": ["sh", "{envelope_file}"]},
            "recipient_policy": {"allowed_recipients": ["test@example.com"], "allowed_domains": []},
        }
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.validate_extension_manifest(base)
        base["executor"] = {"type": "agent"}
        base["recipient_policy"] = {"allowed_recipients": [], "allowed_domains": []}
        with self.assertRaises(swarmctl.SwarmError):
            swarmctl.validate_extension_manifest(base)

    def test_service_case_survives_waits_signals_and_fresh_invocations(self):
        service_root = self.base / "service" / ".swarm"
        swarmctl.initialize(
            service_root,
            "Continuously handle incoming engineering reviews",
            ["Every accepted request reaches a durable disposition"],
            ["Human approval authority may not be inferred"],
            mode="SERVICE",
        )
        payload = self.base / "change.json"
        payload.write_text('{"ref":"change/123","revision":"abc"}\n', encoding="utf-8")
        conn = swarmctl.connect(service_root)
        try:
            self.assertEqual(swarmctl.mission_mode(conn), "SERVICE")
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.complete_mission(conn, "idle", "manager")
            opened = swarmctl.open_case(
                service_root, conn, "review-provider", "change-123", "Review change 123",
                "Produce an independent review and durable disposition", 70, "webhook",
                ["Disposition is supported by evidence"], payload,
                ["repository=example/service"], ready=True,
            )
            self.assertTrue(opened["created"])
            self.assertEqual(opened["status"], "ACTIVE")
            duplicate = swarmctl.open_case(
                service_root, conn, "review-provider", "change-123", "Review change 123",
                "Produce an independent review and durable disposition", 70, "webhook",
                ["Disposition is supported by evidence"], payload,
                ["repository=example/service"], ready=True,
            )
            self.assertFalse(duplicate["created"])
            self.assertEqual(duplicate["id"], opened["id"])
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.open_case(
                    service_root, conn, "review-provider", "change-123", "Review change 123",
                    "Produce an independent review and durable disposition", 70, "webhook",
                    ["A different acceptance contract"], payload,
                    ["repository=example/service"], ready=True,
                )
            task_id = opened["tasks"][0]["id"]
            swarmctl.claim_task(conn, task_id, "reviewer-one", 1800)
            decision_id = swarmctl.block_task(
                conn, task_id, "reviewer-one", "external_dependency",
                "Has the author addressed the requested change?", "Wait for a new revision",
                ["Addressed", "Not addressed"],
            )
            swarmctl.reconcile_conn(conn)
            self.assertEqual(swarmctl.case_row(conn, opened["id"])["status"], "WAITING_EXTERNAL")
            response = swarmctl.add_case_signal(
                service_root, conn, opened["id"], "review-provider", "event-9001",
                "author_response", "author@example.com", "Revision def addresses the finding",
                "webhook", decision_id=decision_id,
            )
            self.assertTrue(response["created"])
            self.assertEqual(swarmctl.task_row(conn, task_id)["status"], "READY")
            repeated = swarmctl.add_case_signal(
                service_root, conn, opened["id"], "review-provider", "event-9001",
                "author_response", "author@example.com", "Revision def addresses the finding",
                "webhook", decision_id=decision_id,
            )
            self.assertFalse(repeated["created"])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS n FROM case_signals").fetchone()["n"], 1
            )
            swarmctl.claim_task(conn, task_id, "reviewer-two", 1800)
            prompt = swarmctl.build_prompt(service_root, "worker", "reviewer-two", task_id)
            self.assertIn("Revision def addresses the finding", prompt)
            self.assertIn("change-123", prompt)
            swarmctl.acknowledge_decision(conn, decision_id, task_id, "reviewer-two")
            swarmctl.complete_task(
                conn, task_id, "reviewer-two", "Author response verified",
                ["Revision def independently verified"], [],
            )
            self.assertEqual(swarmctl.case_row(conn, opened["id"])["status"], "DONE")
            wake = swarmctl.add_case_signal(
                service_root, conn, opened["id"], "review-provider", "event-9002",
                "new_revision", "author@example.com", "Revision ghi was uploaded",
                "webhook", wake=True,
            )
            self.assertTrue(wake["created"])
            self.assertIsNotNone(wake["wake_task_id"])
            current = swarmctl.case_dict(conn, swarmctl.case_row(conn, opened["id"]))
            self.assertEqual(current["status"], "ACTIVE")
            self.assertEqual(len(current["tasks"]), 2)
            self.assertEqual(current["tasks"][-1]["status"], "READY")
            self.assertTrue(swarmctl.doctor(conn)["ok"])
        finally:
            conn.close()

        audit = self.base / "service-audit.zip"
        swarmctl.export_audit(service_root, audit)
        with zipfile.ZipFile(str(audit)) as archive:
            names = set(archive.namelist())
            self.assertTrue(any(name.startswith("swarm-audit/intake/") for name in names))
            snapshot = json.loads(archive.read("swarm-audit/snapshot.json"))
            self.assertEqual(snapshot["mission"]["mode"], "SERVICE")
            self.assertEqual(len(snapshot["cases"]), 1)

    def test_case_can_start_a_generic_policy_workflow(self):
        policy_source = PACKAGE_ROOT / "examples" / "policy-packs" / "human-gated-change-review"
        payload = self.base / "review-request.json"
        payload.write_text('{"change":"https://review.example/42"}\n', encoding="utf-8")
        conn = self.connection()
        try:
            swarmctl.install_policy(conn, policy_source, "human")
            opened = swarmctl.open_case(
                self.root, conn, "review-provider", "42", "Review change 42",
                "Reach a human-authorized disposition", 80, "webhook", [], payload, [],
                "human-gated-change-review",
                [
                    "change_ref=https://review.example/42",
                    "review_skill=adversarial-review",
                    "verification_command=python3 -m unittest",
                ], True,
            )
            self.assertEqual(len(opened["tasks"]), 4)
            self.assertIsNotNone(opened["policy_application_id"])
            self.assertEqual(opened["tasks"][0]["status"], "READY")
            prompt = swarmctl.build_prompt(
                self.root, "verifier", "cold-reviewer", opened["tasks"][0]["id"]
            )
            self.assertIn("human-gated-change-review", prompt)
            self.assertIn("https://review.example/42", prompt)
        finally:
            conn.close()

    def test_case_cli_opens_and_reads_idempotent_request(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = swarmctl.main([
                "--root", str(self.root), "case", "open",
                "--source", "manual", "--external-id", "request-1",
                "--title", "Review request one",
                "--objective", "Return an evidence-backed disposition",
                "--acceptance", "Disposition is recorded", "--ready",
            ])
        self.assertEqual(exit_code, 0)
        opened = json.loads(output.getvalue())
        self.assertTrue(opened["created"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = swarmctl.main([
                "--root", str(self.root), "case", "show", opened["id"],
            ])
        self.assertEqual(exit_code, 0)
        shown = json.loads(output.getvalue())
        self.assertEqual(shown["external_id"], "request-1")
        self.assertEqual(shown["tasks"][0]["status"], "READY")

    def test_setup_check_rejects_unconfigured_runner(self):
        result = swarmctl.setup_check(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("non-empty array" in error for error in result["errors"]))

    def test_setup_check_accepts_valid_local_runner(self):
        config_path = self.root / "runner.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["command"] = [
            sys.executable, "-c", "print('setup probe')", "{prompt_file}",
        ]
        config["working_directory"] = str(self.base)
        config_path.write_text(json.dumps(config), encoding="utf-8")

        result = swarmctl.setup_check(self.root)
        self.assertTrue(result["ok"], result)
        checks = {item["name"]: item for item in result["checks"]}
        self.assertTrue(checks["runner_executable"]["ok"])
        self.assertTrue(checks["prompt_dry_run"]["ok"])
        self.assertEqual(
            len(list((self.root / "prompts").glob("P-*-manager.md"))), 1
        )

    def configure_responsive_runner(self, max_parallel=2):
        config_path = self.root / "runner.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["command"] = [sys.executable, "-c", "pass", "{prompt_file}"]
        config["max_parallel"] = max_parallel
        config["scheduler_poll_seconds"] = 0.01
        config["manager_review_debounce_seconds"] = 0
        config_path.write_text(json.dumps(config), encoding="utf-8")

    @staticmethod
    def future_time(hours):
        value = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(hours=hours)
        return value.isoformat().replace("+00:00", "Z")

    def test_acceptance_1_mixed_duration_work_replans_before_slow_task_ends(self):
        self.configure_responsive_runner(max_parallel=2)
        follow_started = threading.Event()
        slow_finished = threading.Event()
        manager_calls = []

        def fake_dispatch(root, role, agent, task_id=None, dry_run=False):
            conn = swarmctl.connect(root)
            try:
                if role == "manager":
                    manager_calls.append(time.monotonic())
                    tasks = conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
                    titles = {row["title"] for row in tasks}
                    if not tasks:
                        swarmctl.add_task(conn, "Fast evidence", "Return quickly", "discovery",
                                          ["Evidence recorded"], [], 80, "manager", True)
                        swarmctl.add_task(conn, "Slow evidence", "Remain active", "discovery",
                                          ["Evidence recorded"], [], 70, "manager", True)
                    elif "Follow fast evidence" not in titles and any(
                        row["title"] == "Fast evidence" and row["status"] == "DONE" for row in tasks
                    ):
                        swarmctl.add_task(conn, "Follow fast evidence", "Act on the quick result",
                                          "discovery", ["Follow-up recorded"], [], 75,
                                          "manager", True)
                    elif tasks and all(row["status"] in swarmctl.TERMINAL_TASK_STATES for row in tasks):
                        swarmctl.complete_mission(conn, "All responsive work verified", "manager")
                else:
                    task = swarmctl.task_row(conn, task_id)
                    if task["title"] == "Fast evidence":
                        swarmctl.complete_task(conn, task_id, agent, "Fast result",
                                               ["Fast evidence verified"], [])
                    elif task["title"] == "Slow evidence":
                        self.assertTrue(follow_started.wait(3), "follow-up did not start responsively")
                        slow_finished.set()
                        swarmctl.complete_task(conn, task_id, agent, "Slow result",
                                               ["Slow evidence verified"], [])
                    else:
                        self.assertFalse(slow_finished.is_set())
                        follow_started.set()
                        swarmctl.complete_task(conn, task_id, agent, "Follow-up result",
                                               ["Follow-up verified"], [])
            finally:
                conn.close()
            return {"run_id": "fake-%s" % agent, "exit_code": 0}

        with mock.patch.object(runtime, "dispatch", side_effect=fake_dispatch):
            result = swarmctl.run_loop(self.root, 10)
        self.assertEqual(result["state"], "DONE")
        self.assertTrue(follow_started.is_set())
        self.assertGreaterEqual(len(manager_calls), 3)

    def test_acceptance_2_material_finding_is_triaged_while_worker_remains_active(self):
        self.configure_responsive_runner(max_parallel=2)
        triaged = threading.Event()
        worker_finished = threading.Event()
        observed_active_at_triage = []

        def fake_dispatch(root, role, agent, task_id=None, dry_run=False):
            conn = swarmctl.connect(root)
            try:
                if role == "manager":
                    task = conn.execute("SELECT * FROM tasks LIMIT 1").fetchone()
                    finding = conn.execute("SELECT * FROM findings LIMIT 1").fetchone()
                    if not task:
                        swarmctl.add_task(conn, "Inspect retries", "Inspect replay behavior", "discovery",
                                          ["Behavior explained"], [], 80, "manager", True)
                    elif finding and finding["status"] == "OPEN":
                        observed_active_at_triage.append(
                            swarmctl.task_row(conn, task["id"])["status"] in swarmctl.ACTIVE_TASK_STATES
                        )
                        swarmctl.dispose_finding(
                            conn, finding["id"], "DEFERRED", "Bounded task should finish first",
                            "manager",
                        )
                        triaged.set()
                    elif task["status"] == "DONE":
                        swarmctl.complete_mission(conn, "Finding triaged and task verified", "manager")
                else:
                    swarmctl.raise_finding(
                        conn, task_id, agent, "MATERIAL", "Retries may duplicate records",
                        ["log:event-42", "src/retry.py:18"],
                        "May require a replay-safety workstream", "Inspect idempotency boundaries",
                    )
                    self.assertTrue(triaged.wait(3), "manager did not triage in-flight finding")
                    swarmctl.complete_task(conn, task_id, agent, "Retry behavior explained",
                                           ["Relevant retry path inspected"], [])
                    worker_finished.set()
            finally:
                conn.close()
            return {"run_id": "fake-%s" % agent, "exit_code": 0}

        with mock.patch.object(runtime, "dispatch", side_effect=fake_dispatch):
            result = swarmctl.run_loop(self.root, 8)
        self.assertEqual(result["state"], "DONE")
        self.assertEqual(observed_active_at_triage, [True])
        self.assertTrue(worker_finished.is_set())

    def test_acceptance_3_external_polling_uses_fresh_short_checks(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(conn, "Watch pipeline", "Verify provider job", "verification",
                                     ["Provider result verified"], [], 80, "manager", True)
            deadline = self.future_time(8)
            for attempt in range(1, 4):
                agent = "poller-%d" % attempt
                swarmctl.claim_task(conn, task, agent, 1800)
                wait = swarmctl.start_external_wait(
                    conn, task, agent, "Pipeline job is terminal", "job-123", deadline,
                    self.future_time(attempt), signal_expected=True,
                )
                self.assertEqual(wait["status"], "WAITING")
                self.assertIsNone(swarmctl.task_row(conn, task)["owner"])
                swarmctl.reconcile_conn(conn, at=self.future_time(attempt))
                self.assertEqual(swarmctl.task_row(conn, task)["status"], "READY")
            swarmctl.claim_task(conn, task, "poller-4", 1800)
            swarmctl.complete_task(conn, task, "poller-4", "Pipeline succeeded",
                                   ["Queried provider job-123 and verified terminal output"], [])
            waits = conn.execute("SELECT * FROM external_waits ORDER BY created_at").fetchall()
            self.assertEqual(len(waits), 3)
            self.assertTrue(all(row["status"] == "WOKEN" for row in waits))
            self.assertTrue(all(row["wake_reason"] == "SCHEDULED_CHECK" for row in waits))
            self.assertEqual(swarmctl.task_row(conn, task)["generation"], 4)
        finally:
            conn.close()

    def test_acceptance_4_repeated_concurrent_signals_wake_once_and_require_verification(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(conn, "Watch import", "Verify import completion", "verification",
                                     ["Import verified"], [], 80, "manager", True)
            swarmctl.claim_task(conn, task, "watcher", 1800)
            wait = swarmctl.start_external_wait(
                conn, task, "watcher", "Import is terminal", "import-99",
                self.future_time(4), signal_expected=True,
            )
        finally:
            conn.close()

        def send(index):
            local = self.connection()
            try:
                return swarmctl.signal_external_wait(
                    local, wait["id"], "provider", "callback-%d" % index,
                    "webhook", "provider reports completion",
                )
            finally:
                local.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            signals = list(pool.map(send, [1, 2]))
        self.assertEqual(sum(1 for item in signals if item["woke"]), 1)
        replay = send(1)
        self.assertFalse(replay["signal_created"])
        self.assertFalse(replay["woke"])
        conn = self.connection()
        try:
            task_row = swarmctl.task_row(conn, task)
            self.assertEqual(task_row["status"], "READY")
            self.assertIn("Verify external condition", task_row["next_action"])
            self.assertIsNone(task_row["result"])
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) AS n FROM external_waits WHERE id=? AND status='WOKEN'",
                (wait["id"],),
            ).fetchone()["n"], 1)
            swarmctl.claim_task(conn, task, "verifier-after-signal", 1800)
            swarmctl.complete_task(
                conn, task, "verifier-after-signal", "Import completed",
                ["Queried import-99 after the callback and verified provider output"], [],
            )
            self.assertEqual(swarmctl.task_row(conn, task)["status"], "DONE")
        finally:
            conn.close()

    def test_acceptance_5_deadline_wakes_for_attention_without_success(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(conn, "Watch deployment", "Verify deployment", "verification",
                                     ["Deployment verified"], [], 80, "manager", True)
            swarmctl.claim_task(conn, task, "watcher", 1800)
            deadline = self.future_time(2)
            wait = swarmctl.start_external_wait(
                conn, task, "watcher", "Deployment is terminal", "deploy-77",
                deadline, signal_expected=True,
            )
            swarmctl.reconcile_conn(conn, at=self.future_time(3))
            current_wait = swarmctl.external_wait_dict(conn, swarmctl.external_wait_row(conn, wait["id"]))
            self.assertEqual(current_wait["wake_reason"], "DEADLINE")
            self.assertTrue(current_wait["requires_attention"])
            self.assertEqual(swarmctl.task_row(conn, task)["status"], "READY")
            self.assertIsNone(swarmctl.task_row(conn, task)["result"])
        finally:
            conn.close()
        report = swarmctl.render_status_report(self.root).read_text(encoding="utf-8")
        self.assertIn("reached its deadline", report)
        self.assertIn("not assumed successful", report)

    def test_acceptance_6_restart_preserves_wait_finding_and_history(self):
        conn = self.connection()
        task = swarmctl.add_task(conn, "Observe job", "Inspect an external job", "discovery",
                                 ["Job state recorded"], [], 70, "manager", True)
        swarmctl.claim_task(conn, task, "observer", 1800)
        finding = swarmctl.raise_finding(
            conn, task, "observer", "MATERIAL", "Job metadata is inconsistent",
            ["provider:job-5", "event:E-5"], "May invalidate the planned recovery",
            "Compare provider and destination state",
        )
        wait = swarmctl.start_external_wait(
            conn, task, "observer", "Job reaches a terminal state", "job-5",
            self.future_time(5), self.future_time(2), True,
        )
        conn.close()

        restarted = self.connection()
        try:
            self.assertEqual(swarmctl.task_row(restarted, task)["status"], "WAITING_EXTERNAL")
            self.assertEqual(swarmctl.external_wait_row(restarted, wait["id"])["condition"],
                             "Job reaches a terminal state")
            self.assertEqual(swarmctl.finding_row(restarted, finding)["status"], "OPEN")
            events = [row["event_type"] for row in restarted.execute("SELECT * FROM events ORDER BY seq")]
            self.assertIn("FINDING_RAISED", events)
            self.assertIn("EXTERNAL_WAIT_STARTED", events)
            self.assertTrue(swarmctl.doctor(restarted)["ok"])
        finally:
            restarted.close()

    def test_acceptance_7_findings_receive_all_dispositions_and_audit_links(self):
        conn = self.connection()
        try:
            stream = swarmctl.add_workstream(conn, "Replay safety", "Prove replay is safe",
                                             "manager", "ACTIVE")
            source_tasks = []
            finding_ids = []
            for index in range(3):
                task = swarmctl.add_task(
                    conn, "Source %d" % index, "Gather evidence", "discovery",
                    ["Evidence recorded"], [], 60 - index, "manager", True, stream,
                )
                source_tasks.append(task)
                agent = "finder-%d" % index
                swarmctl.claim_task(conn, task, agent, 1800)
                finding_ids.append(swarmctl.raise_finding(
                    conn, task, agent, "MATERIAL", "Finding %d" % index,
                    ["artifact:%d" % index], "Could change replay planning", "Bounded follow-up",
                ))
                swarmctl.complete_task(conn, task, agent, "Evidence gathered",
                                       ["Evidence %d verified" % index], [])
            with self.assertRaises(swarmctl.SwarmError):
                swarmctl.complete_mission(conn, "Too early", "manager")
            follow = swarmctl.add_task(conn, "Investigate first finding", "Bounded follow-up",
                                       "discovery", ["Finding resolved"], [], 55,
                                       "manager", False, stream)
            swarmctl.dispose_finding(conn, finding_ids[0], "INCORPORATED", "Creates bounded work",
                                     "manager", [follow], [stream])
            swarmctl.dispose_finding(conn, finding_ids[1], "DEFERRED", "Useful but not on critical path",
                                     "manager")
            swarmctl.dispose_finding(conn, finding_ids[2], "DISMISSED", "Evidence duplicates known behavior",
                                     "manager")
            states = [swarmctl.finding_row(conn, value)["status"] for value in finding_ids]
            self.assertEqual(states, ["INCORPORATED", "DEFERRED", "DISMISSED"])
        finally:
            conn.close()
        audit = self.base / "finding-audit.zip"
        swarmctl.export_audit(self.root, audit)
        with zipfile.ZipFile(str(audit)) as archive:
            snapshot = json.loads(archive.read("swarm-audit/snapshot.json"))
            incorporated = next(item for item in snapshot["findings"] if item["id"] == finding_ids[0])
            self.assertEqual(incorporated["resulting_tasks"], [follow])
            events = [json.loads(line) for line in archive.read("swarm-audit/events.jsonl").decode().splitlines()]
            dispositions = [item for item in events if item["event_type"] == "FINDING_DISPOSITIONED"]
            self.assertEqual(len(dispositions), 3)

    def test_acceptance_8_routine_checkpoints_do_not_churn_manager(self):
        self.configure_responsive_runner(max_parallel=2)
        manager_calls = []

        def fake_dispatch(root, role, agent, task_id=None, dry_run=False):
            conn = swarmctl.connect(root)
            try:
                if role == "manager":
                    manager_calls.append(time.monotonic())
                    task = conn.execute("SELECT * FROM tasks LIMIT 1").fetchone()
                    if not task:
                        swarmctl.add_task(conn, "Routine work", "Checkpoint normally", "discovery",
                                          ["Work verified"], [], 50, "manager", True)
                    elif task["status"] == "DONE":
                        swarmctl.complete_mission(conn, "Routine work verified", "manager")
                else:
                    for index in range(5):
                        swarmctl.checkpoint_task(
                            conn, task_id, agent, "Routine checkpoint %d" % index,
                            "Continue bounded work", 1800,
                        )
                        time.sleep(0.02)
                    self.assertEqual(conn.execute(
                        "SELECT COUNT(*) AS n FROM manager_reviews WHERE status='PENDING'"
                    ).fetchone()["n"], 0)
                    swarmctl.complete_task(conn, task_id, agent, "Routine work done",
                                           ["Final state verified"], [])
            finally:
                conn.close()
            return {"run_id": "fake-%s" % agent, "exit_code": 0}

        with mock.patch.object(runtime, "dispatch", side_effect=fake_dispatch):
            result = swarmctl.run_loop(self.root, 6)
        self.assertEqual(result["state"], "DONE")
        self.assertEqual(len(manager_calls), 2)

    def test_responsive_cli_round_trip_for_finding_and_external_wait(self):
        conn = self.connection()
        try:
            task = swarmctl.add_task(
                conn, "Inspect provider", "Inspect provider state", "discovery",
                ["Provider state verified"], [], 70, "manager", True,
            )
            swarmctl.claim_task(conn, task, "worker-cli", 1800)
        finally:
            conn.close()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(swarmctl.main([
                "--root", str(self.root), "finding", "raise",
                "--task", task, "--agent", "worker-cli", "--significance", "material",
                "--summary", "Provider state contradicts the plan",
                "--evidence", "provider:job-17", "--impact", "Recovery may need another step",
                "--recommendation", "Inspect the provider result",
            ]), 0)
        finding = json.loads(output.getvalue())
        self.assertEqual(finding["status"], "OPEN")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(swarmctl.main([
                "--root", str(self.root), "task", "wait-external", task,
                "--agent", "worker-cli", "--condition", "Provider job is terminal",
                "--external-ref", "job-17", "--deadline", self.future_time(4),
                "--signal-expected",
            ]), 0)
        wait = json.loads(output.getvalue())
        self.assertEqual(wait["status"], "WAITING")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(swarmctl.main([
                "--root", str(self.root), "wait", "signal", wait["id"],
                "--source", "provider", "--external-id", "callback-17",
                "--note", "Terminal notification",
            ]), 0)
        signal = json.loads(output.getvalue())
        self.assertTrue(signal["woke"])
        self.assertEqual(signal["wake_reason"], "EXTERNAL_SIGNAL")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(swarmctl.main([
                "--root", str(self.root), "finding", "disposition", finding["id"],
                "--status", "deferred", "--rationale", "Verify the wake first",
            ]), 0)
        disposition = json.loads(output.getvalue())
        self.assertEqual(disposition["status"], "DEFERRED")

    def test_external_wait_survives_the_dispatch_process_exit(self):
        self.configure_responsive_runner(max_parallel=2)
        task_ids = []

        def fake_dispatch(root, role, agent, task_id=None, dry_run=False):
            conn = swarmctl.connect(root)
            try:
                if role == "manager":
                    if not task_ids:
                        task_ids.append(swarmctl.add_task(
                            conn, "Wait for provider", "Verify provider completion", "verification",
                            ["Provider completion verified"], [], 70, "manager", True,
                        ))
                else:
                    swarmctl.start_external_wait(
                        conn, task_id, agent, "Provider job is terminal", "job-process-exit",
                        self.future_time(4), signal_expected=True,
                    )
            finally:
                conn.close()
            return {"run_id": "fake-%s" % agent, "exit_code": 0}

        with mock.patch.object(runtime, "dispatch", side_effect=fake_dispatch):
            result = swarmctl.run_loop(self.root, 4)
        self.assertEqual(result["state"], "WAITING_EXTERNAL")
        conn = self.connection()
        try:
            row = swarmctl.task_row(conn, task_ids[0])
            self.assertEqual(row["status"], "WAITING_EXTERNAL")
            self.assertIsNone(row["owner"])
            self.assertIsNone(row["lease_until"])
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) AS n FROM external_waits WHERE task_id=? AND status='WAITING'",
                (task_ids[0],),
            ).fetchone()["n"], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
