"""Workspace adapters must work in source directories with no Git metadata."""

import contextlib
import io
import json
import os
import signal
import subprocess
import time
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from swarmkit import workspaces

import swarmctl as s


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-workspaces-")
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / ".swarm"
        self.source = self.base / "monorepo with spaces"
        self.source.mkdir()
        s.initialize(self.root, "VCS-neutral work", ["Verified"], [])
        self.conn = s.connect(self.root)
        self.task = s.add_task(
            self.conn, "Inspect", "Inspect", "discovery", ["Checked"], [], 50, "manager", True
        )

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def configure(self, workspace):
        path = self.root / "runner.json"
        config = json.loads(path.read_text())
        config["workspace"] = workspace
        path.write_text(json.dumps(config))

    def adapter(self):
        script = self.base / "internal checkout adapter.py"
        script.write_text(
            """import json,sys
from pathlib import Path
source, destination, base, task = sys.argv[1:]
path = Path(destination)
path.mkdir()
(path / 'request.json').write_text(json.dumps({'source':source,'base':base,'task':task}))
print(json.dumps({'path':str(path),'base_revision':'internal-revision:42','workspace_ref':'jj-workspace:'+task}))
"""
        )
        self.configure(
            {
                "provider": "command",
                "command": [
                    sys.executable,
                    str(script),
                    "{repository}",
                    "{path}",
                    "{base}",
                    "{task_id}",
                ],
            }
        )

    def test_no_implicit_git_and_manual_registration_dispatches_in_checkout(self):
        with (
            mock.patch.object(workspaces.subprocess, "Popen") as process,
            mock.patch.object(workspaces.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(s.SwarmError, "No workspace creation provider"):
                s.create_workspace(self.root, self.conn, self.task, self.source, "trunk()")
            process.assert_not_called()
            run.assert_not_called()
        checkout = self.base / "internal checkout"
        checkout.mkdir()
        row = s.register_workspace(self.conn, self.task, self.source, checkout, "opaque-revision")
        self.assertEqual(row["provider"], "manual")
        self.assertEqual(row["workspace_ref"], "")
        config_path = self.root / "runner.json"
        config = json.loads(config_path.read_text())
        config["command"] = [sys.executable, "-c", "import os; print(os.getcwd())"]
        config_path.write_text(json.dumps(config))
        s.claim_task(self.conn, self.task, "agent", 600)
        result = s.dispatch(self.root, "worker", "agent", self.task)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(Path(result["stdout"]).read_text().strip(), str(checkout))

    def test_command_receipt_and_opaque_revision_are_preserved_without_git(self):
        self.adapter()
        expression = "trunk() & ancestors(@) $(touch never)"
        with mock.patch.object(
            workspaces.subprocess, "run", side_effect=AssertionError("Git must not be invoked")
        ):
            row = s.create_workspace(self.root, self.conn, self.task, self.source, expression)
        self.assertEqual(row["base_revision"], "internal-revision:42")
        self.assertEqual(row["provider"], "command")
        self.assertEqual(row["requested_base"], expression)
        recorded = json.loads((Path(row["path"]) / "request.json").read_text())
        self.assertEqual(
            recorded, {"source": str(self.source), "base": expression, "task": self.task}
        )
        with mock.patch.object(
            workspaces.subprocess,
            "Popen",
            side_effect=AssertionError("Retry must not create again"),
        ):
            self.assertEqual(
                s.create_workspace(self.root, self.conn, self.task, self.source, expression), row
            )
        with self.assertRaisesRegex(s.SwarmError, "different base"):
            s.create_workspace(self.root, self.conn, self.task, self.source, "other()")

    def test_bad_receipt_failure_timeout_and_unknown_placeholders_do_not_register(self):
        for code, expected in [
            ('print("not json")', "JSON"),
            ('print("{}")', "absolute path"),
            ("raise SystemExit(3)", "failed"),
            ("import time; time.sleep(10)", "timed out"),
        ]:
            with self.subTest(code=code):
                self.configure(
                    {
                        "provider": "command",
                        "command": [
                            sys.executable,
                            "-c",
                            code.replace("{", "{{").replace("}", "}}"),
                        ],
                        "timeout_seconds": 1,
                    }
                )
                with self.assertRaisesRegex(s.SwarmError, expected):
                    s.create_workspace(self.root, self.conn, self.task, self.source, "opaque")
                self.assertEqual(
                    self.conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0], 0
                )
                pending = workspaces.pending_creation(self.conn, self.task)
                workspaces.reconcile_workspace(
                    self.root,
                    self.conn,
                    pending["id"],
                    "not-created",
                    "Test adapter did not create any checkout",
                )
        self.configure({"provider": "command", "command": ["tool", "{unknown}"]})
        with mock.patch.object(workspaces.subprocess, "Popen") as process:
            with self.assertRaisesRegex(s.SwarmError, "placeholder"):
                s.create_workspace(self.root, self.conn, self.task, self.source, "opaque")
            process.assert_not_called()

    def test_registration_checks_isolation_ownership_and_immutable_binding(self):
        checkout = self.base / "checkout"
        checkout.mkdir()
        with self.assertRaisesRegex(s.SwarmError, "source directory"):
            s.register_workspace(self.conn, self.task, self.source, self.source, "revision")
        s.claim_task(self.conn, self.task, "owner", 600)
        with self.assertRaises(s.SwarmError):
            s.register_workspace(
                self.conn, self.task, self.source, checkout, "revision", agent="stale"
            )
        row = s.register_workspace(
            self.conn, self.task, self.source, checkout, "revision", "workspace-name", agent="owner"
        )
        self.assertEqual(
            row,
            s.register_workspace(
                self.conn,
                self.task,
                self.source,
                checkout,
                "revision",
                "workspace-name",
                agent="owner",
            ),
        )
        with self.assertRaisesRegex(s.SwarmError, "immutable"):
            s.register_workspace(
                self.conn, self.task, self.source, checkout, "other-revision", agent="owner"
            )
        other = s.add_task(
            self.conn, "Other", "Other", "discovery", ["Checked"], [], 50, "manager", True
        )
        with self.assertRaisesRegex(s.SwarmError, "another task"):
            s.register_workspace(self.conn, other, self.source, checkout, "revision")

    def test_current_owner_can_create_configured_workspace_from_cli(self):
        self.adapter()
        s.claim_task(self.conn, self.task, "owner", 600)
        with mock.patch.object(workspaces.subprocess, "Popen") as process:
            with self.assertRaises(s.SwarmError):
                s.create_workspace(
                    self.root, self.conn, self.task, self.source, "trunk()", agent="stale"
                )
            process.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = s.main(
                [
                    "--root",
                    str(self.root),
                    "workspace",
                    "create",
                    "--task",
                    self.task,
                    "--repository",
                    str(self.source),
                    "--base",
                    "trunk()",
                    "--agent",
                    "owner",
                ]
            )
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["provider"], "command")

    def test_checkout_child_retains_lock_after_controller_is_killed(self):
        ready = self.base / "checkout-child.pid"
        code = (
            "import os,time; from pathlib import Path; Path(%r).write_text(str(os.getpid())); time.sleep(30)"
            % str(ready)
        )
        self.configure({"provider": "command", "command": [sys.executable, "-c", code]})
        command = [
            sys.executable,
            "-B",
            str(Path(s.__file__)),
            "--root",
            str(self.root),
            "workspace",
            "create",
            "--task",
            self.task,
            "--repository",
            str(self.source),
            "--base",
            "trunk()",
        ]
        controller = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child = None
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists(), "Checkout adapter did not start")
            child = int(ready.read_text())
            controller.kill()
            controller.wait(timeout=5)
            pending = workspaces.pending_creation(self.conn, self.task)
            self.assertEqual(pending["state"], "UNKNOWN")
            with self.assertRaisesRegex(s.SwarmError, "Another process"):
                workspaces.reconcile_workspace(
                    self.root, self.conn, pending["id"], "not-created", "Cannot yet prove this"
                )
            with self.assertRaises(s.SwarmError):
                with s.process_lock(self.root / "workspaces.lock"):
                    pass
        finally:
            if controller.poll() is None:
                controller.kill()
            controller.wait(timeout=5)
            if child:
                try:
                    os.killpg(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_lost_receipt_at_provider_allocated_path_never_replays(self):
        checkout = self.base / "provider allocated checkout"
        counter = self.base / "invocations"
        script = self.base / "lost-receipt.py"
        script.write_text(
            "from pathlib import Path\n"
            "p=Path(%r); p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
            "Path(%r).mkdir(exist_ok=True)\nprint('receipt lost')\n" % (str(counter), str(checkout))
        )
        self.configure({"provider": "command", "command": [sys.executable, str(script)]})
        with self.assertRaisesRegex(s.SwarmError, "JSON"):
            s.create_workspace(self.root, self.conn, self.task, self.source, "trunk()")
        pending = workspaces.pending_creation(self.conn, self.task)
        self.assertEqual(pending["state"], "UNKNOWN")
        self.assertIn("receipt lost", Path(pending["stdout_path"]).read_text())
        self.conn.close()
        self.conn = s.connect(self.root)
        with self.assertRaisesRegex(s.SwarmError, "requires reconciliation"):
            s.create_workspace(self.root, self.conn, self.task, self.source, "trunk()")
        with self.assertRaisesRegex(s.SwarmError, "requires reconciliation"):
            s.register_workspace(self.conn, self.task, self.source, checkout, "exact:42")
        config_path = self.root / "runner.json"
        config = json.loads(config_path.read_text())
        config["command"] = [sys.executable, "-c", "pass"]
        config_path.write_text(json.dumps(config))
        with self.assertRaisesRegex(s.SwarmError, "before dispatch"):
            s.dispatch(self.root, "worker", "owner", self.task, dry_run=True)
        receipt = {"path": str(checkout), "base_revision": "exact:42", "workspace_ref": "jj:name"}
        workspaces.reconcile_workspace(
            self.root,
            self.conn,
            pending["id"],
            "created",
            "Internal CLI lookup returned this checkout",
            receipt,
        )
        registered = s.create_workspace(self.root, self.conn, self.task, self.source, "trunk()")
        self.assertEqual(registered["path"], str(checkout))
        self.assertEqual(registered["workspace_ref"], "jj:name")
        self.assertEqual(counter.read_text(), "x")
        retried = workspaces.reconcile_workspace(
            self.root, self.conn, pending["id"], "created", "Repeated provider observation", receipt
        )
        self.assertEqual(retried["state"], "REGISTERED")
        self.assertEqual(workspaces.creation_row(self.conn, pending["id"])["state"], "REGISTERED")

    def test_success_receipt_survives_expired_owner_before_attachment(self):
        self.adapter()
        s.claim_task(self.conn, self.task, "owner", 600)
        real_run = workspaces.run_logged_process

        def expire_after_provider(*args, **kwargs):
            result = real_run(*args, **kwargs)
            self.conn.execute(
                "UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (self.task,)
            )
            self.conn.commit()
            return result

        with mock.patch.object(workspaces, "run_logged_process", side_effect=expire_after_provider):
            with self.assertRaises(s.SwarmError):
                s.create_workspace(
                    self.root, self.conn, self.task, self.source, "trunk()", agent="owner"
                )
        self.assertEqual(workspaces.pending_creation(self.conn, self.task)["state"], "CREATED")
        s.reconcile_conn(self.conn)
        s.claim_task(self.conn, self.task, "fresh-owner", 600)
        with mock.patch.object(
            workspaces,
            "run_logged_process",
            side_effect=AssertionError("No second provider invocation"),
        ):
            result = s.create_workspace(
                self.root, self.conn, self.task, self.source, "trunk()", agent="fresh-owner"
            )
        self.assertEqual(result["base_revision"], "internal-revision:42")

    def test_creation_inside_transaction_cannot_launch_uncommitted_action(self):
        self.adapter()
        with (
            s.transaction(self.conn),
            mock.patch.object(workspaces, "run_logged_process") as process,
        ):
            with self.assertRaisesRegex(s.SwarmError, "own transaction"):
                s.create_workspace(self.root, self.conn, self.task, self.source, "trunk()")
            process.assert_not_called()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM workspace_creations").fetchone()[0], 0
        )

    def test_proven_launch_failure_can_retry_without_reconciliation(self):
        self.configure({"provider": "command", "command": [str(self.base / "missing-tool")]})
        with self.assertRaisesRegex(s.SwarmError, "failed"):
            s.create_workspace(self.root, self.conn, self.task, self.source, "trunk()")
        row = self.conn.execute("SELECT * FROM workspace_creations").fetchone()
        self.assertEqual(row["state"], "NOT_CREATED")
        self.assertIn("Could not start", Path(row["stderr_path"]).read_text())
        self.adapter()
        self.assertEqual(
            s.create_workspace(self.root, self.conn, self.task, self.source, "trunk()")["provider"],
            "command",
        )

    def test_reconciliation_cli_records_observation_and_is_retryable(self):
        self.configure({"provider": "command", "command": [sys.executable, "-c", "print('lost')"]})
        with self.assertRaises(s.SwarmError):
            s.create_workspace(self.root, self.conn, self.task, self.source, "base")
        pending = workspaces.pending_creation(self.conn, self.task)
        command = [
            "--root",
            str(self.root),
            "workspace",
            "reconcile",
            pending["id"],
            "--outcome",
            "not-created",
            "--observation",
            "Provider lookup found no checkout",
        ]
        with s.process_lock(self.root / "workspaces.lock"):
            with self.assertRaisesRegex(s.SwarmError, "Another process"):
                workspaces.reconcile_workspace(
                    self.root, self.conn, pending["id"], "not-created", "No checkout"
                )
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(s.main(command), 0)
            self.assertEqual(json.loads(output.getvalue())["state"], "NOT_CREATED")
        count = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='WORKSPACE_CREATION_NOT_CREATED'"
        ).fetchone()[0]
        self.assertEqual(count, 1)
        with self.assertRaisesRegex(s.SwarmError, "Only an uncertain"):
            workspaces.reconcile_workspace(
                self.root,
                self.conn,
                pending["id"],
                "created",
                "Conflicting result",
                {"path": str(self.base), "base_revision": "r"},
            )

    def test_uncertain_creation_blocks_drain_resume_and_amendment_until_observed(self):
        self.configure({"provider": "command", "command": [sys.executable, "-c", "print('lost')"]})
        with self.assertRaises(s.SwarmError):
            s.create_workspace(self.root, self.conn, self.task, self.source, "base")
        pending = workspaces.pending_creation(self.conn, self.task)
        s.control_mission(self.conn, "drain", "operator", "Finish owned work")
        s.reconcile_conn(self.conn)
        self.assertEqual(s.runtime_state(self.conn)["desired_state"], "DRAINING")
        s.control_mission(self.conn, "pause", "operator", "Inspect checkout")
        with self.assertRaisesRegex(s.SwarmError, "checkout"):
            s.control_mission(self.conn, "resume", "operator", "Continue")
        with self.assertRaisesRegex(s.SwarmError, "checkout"):
            s.amend_mission(
                self.conn, "New objective", ["Verified"], [], "New information", "operator"
            )
        checkout = self.base / "found checkout"
        checkout.mkdir()
        # Provider observation is allowed during pause, but attachment still needs active state.
        workspaces.reconcile_workspace(
            self.root,
            self.conn,
            pending["id"],
            "created",
            "Located through provider",
            {"path": str(checkout), "base_revision": "r"},
        )
        with self.assertRaisesRegex(s.SwarmError, "not accepting"):
            s.create_workspace(self.root, self.conn, self.task, self.source, "base")
        s.control_mission(self.conn, "resume", "operator", "Provider checked")
        self.assertEqual(
            s.create_workspace(self.root, self.conn, self.task, self.source, "base")["path"],
            str(checkout),
        )

    def test_schema_nine_migration_adds_creation_journal(self):
        self.conn.execute("DROP TABLE workspace_creations")
        self.conn.execute("UPDATE meta SET value='9' WHERE key='schema_version'")
        self.conn.commit()
        self.conn.close()
        self.conn = s.connect(self.root)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM workspace_creations").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            "10",
        )

    def test_migration_preserves_old_git_workspaces(self):
        self.conn.execute("DROP TABLE workspaces")
        self.conn.execute(
            "CREATE TABLE workspaces (task_id TEXT PRIMARY KEY REFERENCES tasks(id),path TEXT NOT NULL UNIQUE,repository TEXT NOT NULL,base_revision TEXT NOT NULL,branch TEXT NOT NULL)"
        )
        self.conn.execute(
            "INSERT INTO workspaces VALUES(?,?,?,?,?)",
            (self.task, "/checkout", "/source", "sha", "branch"),
        )
        self.conn.execute("UPDATE meta SET value='7' WHERE key='schema_version'")
        self.conn.commit()
        self.conn.close()
        self.conn = s.connect(self.root)
        row = dict(self.conn.execute("SELECT * FROM workspaces").fetchone())
        self.assertEqual(row["provider"], "git")
        self.assertEqual(row["base_revision"], "sha")
        self.assertIsNone(row["requested_base"])
        self.assertEqual(
            self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            s.SCHEMA_VERSION,
        )

    def test_register_cli_and_missing_checkout_error(self):
        checkout = self.base / "checkout"
        checkout.mkdir()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(
                s.main(
                    [
                        "--root",
                        str(self.root),
                        "workspace",
                        "register",
                        "--task",
                        self.task,
                        "--repository",
                        str(self.source),
                        "--path",
                        str(checkout),
                        "--base-revision",
                        "internal:42",
                    ]
                ),
                0,
            )
        self.assertEqual(json.loads(output.getvalue())["provider"], "manual")
        checkout.rmdir()
        config_path = self.root / "runner.json"
        config = json.loads(config_path.read_text())
        config["command"] = [sys.executable, "-c", "pass"]
        config_path.write_text(json.dumps(config))
        with self.assertRaisesRegex(s.SwarmError, "workspace is missing"):
            s.dispatch(self.root, "worker", "worker", self.task, dry_run=True)


if __name__ == "__main__":
    unittest.main()
