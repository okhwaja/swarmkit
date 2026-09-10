"""Conditional action scope and event-to-outbox crash/replay contracts."""

import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import delivery, grants, notifications


class GrantsNotificationsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-actions-")
        self.base = Path(self.temp.name)
        self.root = self.base / ".swarm"
        s.initialize(self.root, "Act within recorded scope", ["Receipt verified"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def grant(self, waivable=False):
        task = s.add_task(
            self.conn,
            "Action",
            "Check then act",
            "implementation",
            ["Verified"],
            [],
            50,
            "manager",
            True,
        )
        s.claim_task(self.conn, task, "first", 600)
        decision = s.block_task(
            self.conn, task, "first", "human_decision", "Proceed?", "Proceed", ["Proceed", "Wait"]
        )
        s.resolve_decision(self.conn, decision, "Proceed in scope", "human", "Proceed")
        spec = {
            "provider": "test",
            "action": "submit",
            "resources": ["item-1"],
            "revision": "opaque-revision",
            "environment": "test-host",
            "delegate": "operator",
            "expires_at": "2099-01-01T00:00:00Z",
            "conditions": [
                {
                    "id": "green",
                    "check": "provider-green",
                    "waivable": waivable,
                    "max_age_seconds": 60,
                }
            ],
        }
        grant_id = grants.issue_grant(self.conn, decision, "Proceed", spec, "human")
        s.claim_task(self.conn, task, "worker", 600)
        s.acknowledge_decision(self.conn, decision, task, "worker")
        return task, decision, grant_id

    def record(self, task, grant_id, code=0):
        path = self.base / (
            "check-%d.json"
            % self.conn.execute("SELECT COUNT(*) FROM grant_evaluations").fetchone()[0]
        )
        path.write_text(json.dumps({"exit_code": code}))
        now = s.utcnow()
        expiry = (s.parse_time(now) + dt.timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
        grants.record_condition(
            self.conn,
            grant_id,
            task,
            "worker",
            "green",
            "provider-green",
            "opaque-revision",
            "test-host",
            code,
            path,
            now,
            expiry,
        )
        return path

    def require(self, task, grant_id, **changes):
        values = dict(
            conn=self.conn,
            grant_id=grant_id,
            task_id=task,
            agent="worker",
            provider="test",
            action="submit",
            resource="item-1",
            revision="opaque-revision",
            environment="test-host",
        )
        values.update(changes)
        return grants.require_grant(**values)

    def prepare(self, task, grant_id, key="action-1"):
        from swarmkit.effects import prepare_effect

        return prepare_effect(
            self.conn,
            task,
            "worker",
            key,
            "item-1",
            "opaque-revision",
            {},
            grant_id,
            "test",
            "submit",
            "test-host",
        )

    def test_grant_requires_all_conditions_even_when_waivable(self):
        task, _, grant_id = self.grant(True)
        with self.assertRaises(s.SwarmError):
            self.require(task, grant_id)
        self.record(task, grant_id, 1)
        with self.assertRaises(s.SwarmError):
            self.require(task, grant_id)
        grants.waive_condition(
            self.conn, grant_id, "green", "operator", "Reviewed exception", "2098-01-01T00:00:00Z"
        )
        self.assertIsNotNone(self.require(task, grant_id)[0]["waiver_id"])

    def test_nonwaivable_condition_and_unauthorized_waiver_are_rejected(self):
        task, _, grant_id = self.grant()
        with self.assertRaises(s.SwarmError):
            grants.waive_condition(
                self.conn, grant_id, "green", "human", "Override", "2098-01-01T00:00:00Z"
            )
        self.conn.execute(
            "UPDATE grants SET specification_json=json_replace(specification_json,'$.conditions[0].waivable',json('true'))"
        )
        self.conn.commit()
        with self.assertRaises(s.SwarmError):
            grants.waive_condition(
                self.conn, grant_id, "green", "stranger", "Override", "2098-01-01T00:00:00Z"
            )

    def test_wrong_scope_and_tampered_evidence_cannot_start_an_effect(self):
        task, _, grant_id = self.grant()
        path = self.record(task, grant_id)
        for changes in (
            {"revision": "other"},
            {"environment": "production"},
            {"resource": "item-2"},
            {"action": "mail"},
        ):
            with self.assertRaises(s.SwarmError):
                self.require(task, grant_id, **changes)
        effect = self.prepare(task, grant_id)
        path.write_text("Tampered")
        with self.assertRaises(s.SwarmError):
            s.transition_effect(self.conn, effect["id"], "start", "worker")
        self.assertEqual(self.conn.execute("SELECT state FROM effects").fetchone()[0], "PREPARED")

    def test_lease_expiring_during_grant_hash_cannot_publish_or_start(self):
        from swarmkit import storage

        for operation in ("record", "start"):
            with self.subTest(operation=operation):
                task, _, grant_id = self.grant()
                self.record(task, grant_id)
                effect = self.prepare(task, grant_id, key="lease-" + operation)
                before = dt.datetime.now(dt.timezone.utc)
                hash_file = grants.hash_file
                target = storage if operation == "record" else grants
                evaluations = self.conn.execute(
                    "SELECT COUNT(*) FROM grant_evaluations"
                ).fetchone()[0]
                artifacts = self.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
                with mock.patch.object(storage, "dt") as clock:
                    clock.timezone = dt.timezone
                    clock.datetime.now.return_value = before

                    def slow_hash(path):
                        value = hash_file(path)
                        clock.datetime.now.return_value = before + dt.timedelta(seconds=601)
                        return value

                    with mock.patch.object(target, "hash_file", side_effect=slow_hash):
                        with self.assertRaisesRegex(s.SwarmError, "Lease expired"):
                            if operation == "record":
                                self.record(task, grant_id)
                            else:
                                s.transition_effect(self.conn, effect["id"], "start", "worker")
                self.assertEqual(
                    self.conn.execute(
                        "SELECT state FROM effects WHERE id=?", (effect["id"],)
                    ).fetchone()[0],
                    "PREPARED",
                )
                self.assertEqual(
                    self.conn.execute("SELECT COUNT(*) FROM grant_evaluations").fetchone()[0],
                    evaluations,
                )
                self.assertEqual(
                    self.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], artifacts
                )
                self.assertFalse(
                    self.conn.execute(
                        "SELECT 1 FROM events WHERE event_type='EFFECT_GRANT_CHECKED' AND entity_id=?",
                        (effect["id"],),
                    ).fetchone()
                )

    def test_revocation_between_prepare_and_start_is_enforced(self):
        task, _, grant_id = self.grant()
        self.record(task, grant_id)
        effect = self.prepare(task, grant_id)
        grants.revoke_grant(self.conn, grant_id, "human", "Changed instructions")
        with self.assertRaises(s.SwarmError):
            s.transition_effect(self.conn, effect["id"], "start", "worker")

    def test_revision_invalidates_grant_and_unknown_effect_is_not_replayed(self):
        task, decision, grant_id = self.grant()
        self.record(task, grant_id)
        effect = self.prepare(task, grant_id)
        s.transition_effect(self.conn, effect["id"], "start", "worker")
        s.revise_decision(self.conn, decision, "Hold action", "human", "Wait")
        self.assertEqual(self.conn.execute("SELECT state FROM effects").fetchone()[0], "UNKNOWN")
        with self.assertRaises(s.SwarmError):
            grants.current_grant(self.conn, grant_id)
        with self.assertRaises(s.SwarmError):
            s.transition_effect(self.conn, effect["id"], "start", "worker")
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, task, "fresh", 600)

    def test_grant_binding_cannot_be_removed_by_retry(self):
        task, _, grant_id = self.grant()
        self.record(task, grant_id)
        effect = self.prepare(task, grant_id)
        with self.assertRaises(s.SwarmError):
            s.prepare_effect(self.conn, task, "worker", "action-1", "item-1", "opaque-revision", {})
        self.assertEqual(self.prepare(task, grant_id)["id"], effect["id"])

    def test_expired_result_or_new_failed_result_overrides_old_success(self):
        task, _, grant_id = self.grant()
        self.record(task, grant_id)
        self.conn.execute("UPDATE grant_evaluations SET expires_at='2000-01-01T00:00:00Z'")
        self.conn.commit()
        with self.assertRaises(s.SwarmError):
            self.require(task, grant_id)
        self.record(task, grant_id)
        self.assertTrue(self.require(task, grant_id)[0]["passed"])
        self.record(task, grant_id, 1)
        with self.assertRaises(s.SwarmError):
            self.require(task, grant_id)

    def test_result_record_rolls_back_if_audit_fails(self):
        task, _, grant_id = self.grant()
        with mock.patch.object(grants, "add_event", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.record(task, grant_id)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM grant_evaluations").fetchone()[0], 0
        )

    def test_readonly_example_checks_exact_revision_and_fails_on_missing_data(self):
        path = self.base / "observation.json"
        path.write_text(
            json.dumps(
                {
                    "revision": "r1",
                    "environment": "test",
                    "observed_at": s.utcnow(),
                    "values": {"green": True},
                }
            )
        )
        command = [
            sys.executable,
            "-B",
            str(Path(s.__file__).parent / "examples/check_condition.py"),
            str(path),
            "--revision",
            "r1",
            "--environment",
            "test",
            "--field",
            "green",
            "--equals",
            "true",
        ]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        path.write_text("{}")
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)

    def subscriptions(self):
        folder = self.base / "extension"
        folder.mkdir()
        manifest = {
            "schema_version": 1,
            "id": "test-delivery",
            "version": "1",
            "name": "Test",
            "kind": "delivery",
            "description": "Local test adapter",
            "handles": ["email"],
            "guidance": "GUIDANCE.md",
            "executor": {
                "type": "command",
                "command": [sys.executable, "-c", "print('no receipt')", "{envelope_file}"],
                "timeout_seconds": 5,
            },
            "recipient_policy": {"allowed_recipients": ["test@example.com"], "allowed_domains": []},
        }
        (folder / "extension.json").write_text(json.dumps(manifest))
        (folder / "GUIDANCE.md").write_text("Record a provider receipt.")
        s.install_extension(self.conn, folder, "human")
        spec = {
            "id": "operator",
            "version": 1,
            "extension": "test-delivery",
            "channel": "email",
            "recipients": ["test@example.com"],
            "events": ["DECISION_NEEDS_ATTENTION"],
            "after_seq": 0,
        }
        self.grant()  # Emits one durable attention event without invoking a provider.
        return [spec]

    def test_notification_replay_and_fanout_have_stable_payloads(self):
        specs = self.subscriptions()
        specs.append(dict(specs[0], id="backup"))
        notifications.enqueue_notifications(self.root, self.conn, specs)
        rows = self.conn.execute("SELECT id,content_sha256 FROM deliveries ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["content_sha256"], rows[1]["content_sha256"])
        self.conn.execute("UPDATE notification_subscriptions SET cursor=0")
        self.conn.commit()
        notifications.enqueue_notifications(self.root, self.conn, specs)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 2)

    def test_enqueue_failure_does_not_advance_cursor_and_restart_replays(self):
        specs = self.subscriptions()
        with mock.patch.object(
            delivery, "add_event", side_effect=RuntimeError("Crash before commit")
        ):
            with self.assertRaises(RuntimeError):
                notifications.enqueue_notifications(self.root, self.conn, specs)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM notification_subscriptions").fetchone()[0], 0
        )
        self.conn.close()
        self.conn = s.connect(self.root)
        self.addCleanup(self.conn.close)
        notifications.enqueue_notifications(self.root, self.conn, specs)
        self.assertEqual(len(notifications.pending_notifications(self.conn, 5)), 1)

    def test_unknown_delivery_is_not_automatically_resent(self):
        specs = self.subscriptions()
        notifications.enqueue_notifications(self.root, self.conn, specs)
        identifier = notifications.pending_notifications(self.conn, 1)[0]
        result = s.dispatch_delivery(self.root, identifier, "sender")
        self.assertEqual(result["delivery_status"], "UNKNOWN")
        notifications.enqueue_notifications(self.root, self.conn, specs)
        self.assertEqual(notifications.pending_notifications(self.conn, 5), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM delivery_runs").fetchone()[0], 1)

    def test_route_change_requires_version_and_disabling_stops_dispatch(self):
        specs = self.subscriptions()
        notifications.enqueue_notifications(self.root, self.conn, specs)
        with self.assertRaises(s.SwarmError):
            notifications.enqueue_notifications(self.root, self.conn, [dict(specs[0], after_seq=1)])
        notifications.enqueue_notifications(self.root, self.conn, [])
        self.assertEqual(notifications.pending_notifications(self.conn, 1), [])
        with self.assertRaises(s.SwarmError):
            notifications.enqueue_notifications(
                self.root, self.conn, [dict(specs[0], recipients=["unapproved@example.com"])]
            )

    def test_notification_loop_events_are_rejected(self):
        specs = self.subscriptions()
        with self.assertRaises(s.SwarmError):
            notifications.validate_subscriptions([dict(specs[0], events=["DELIVERY_ENQUEUED"])])

    def test_bounded_consumer_reaches_events_after_first_page(self):
        from swarmkit.storage import add_event

        specs = self.subscriptions()
        specs[0]["after_seq"] = self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0]
        for index in range(150):
            add_event(
                self.conn,
                s.mission(self.conn)["id"],
                "mission",
                "M",
                "LOCAL_PROGRESS",
                "test",
                {"index": index},
            )
        add_event(
            self.conn,
            s.mission(self.conn)["id"],
            "decision",
            "D",
            "DECISION_NEEDS_ATTENTION",
            "test",
            {"question": "Review"},
        )
        self.conn.commit()
        self.assertTrue(notifications.enqueue_notifications(self.root, self.conn, specs))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 0)
        for _ in range(4):
            if not notifications.enqueue_notifications(self.root, self.conn, specs):
                break
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0], 1)

    def test_escalated_review_still_dispatches_its_notification(self):
        specs = self.subscriptions()
        specs[0]["events"] = ["SUPERVISOR_ESCALATED"]
        config = self.root / "runner.json"
        config.write_text(
            json.dumps(
                dict(
                    json.loads(config.read_text()),
                    command=[sys.executable, "-c", "pass"],
                    notifications=specs,
                    manager_review_debounce_seconds=0,
                )
            )
        )
        s.configure_runtime(self.conn, {"max_manager_failures": 1})
        identifier = s.request_manager_review(
            self.conn, "Test failure", "mission", s.mission(self.conn)["id"]
        )[0]
        s.claim_manager_review(self.conn, "failed-manager", 600)
        s.finish_manager_review(self.conn, identifier, "failed-manager", False)
        result = s.run_loop(self.root, 10)
        self.assertEqual(result["state"], "ESCALATED")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM delivery_runs").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT status FROM deliveries").fetchone()[0], "UNKNOWN"
        )
