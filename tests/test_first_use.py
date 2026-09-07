"""The first-use path stays isolated and makes the next action understandable."""

from pathlib import Path
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from swarmkit import cli, views
from swarmkit.core import PACKAGE_ROOT
from swarmkit.setup import initialize
from swarmkit.storage import connect
from swarmkit.tasks import add_task, block_task, claim_task, control_mission


class FirstUseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-first-use-")
        self.directory = Path(self.temp.name).resolve()
        self.root = self.directory / ".swarm"
        initialize(self.root, "Restore delivery", ["Verified"], [])

    def tearDown(self):
        self.temp.cleanup()

    def test_demo_ignores_active_mission_environment_and_refuses_repeat(self):
        env = dict(os.environ, SWARM_ROOT=str(self.root))
        command = [sys.executable, "-B", str(PACKAGE_ROOT / "swarmctl.py"), "demo"]
        result = subprocess.run(
            command, cwd=str(self.directory), env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Synthetic", result.stdout)
        demo = self.directory / "swarm-demo"
        self.assertTrue((demo / "audit.zip").is_file())
        self.assertTrue((demo / ".swarm/views/STATUS.md").is_file())
        conn = connect(self.root)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        finally:
            conn.close()
        result = subprocess.run(
            command, cwd=str(self.directory), env=env, capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_brief_status_does_not_load_full_snapshot(self):
        with mock.patch.object(cli, "mission_snapshot", side_effect=AssertionError("unbounded")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["--root", str(self.root), "status", "--brief"]), 0)
        self.assertIn("Restore delivery", output.getvalue())
        self.assertIn("none yet", output.getvalue())
        self.assertIn("Next:", output.getvalue())

    def test_brief_status_shows_question_and_pause(self):
        conn = connect(self.root)
        try:
            task = add_task(
                conn, "Repair", "Repair", "implementation", ["Verified"], [], 50, "manager", True
            )
            claim_task(conn, task, "worker", 60)
            decision = block_task(
                conn,
                task,
                "worker",
                "human_decision",
                "May ingestion pause?",
                "Pause",
                ["Pause", "Continue"],
            )
            summary = views.brief_status(conn)
            self.assertIn(decision, summary)
            self.assertIn("May ingestion pause?", summary)
            control_mission(conn, "pause", "human", "Waiting")
            self.assertIn("PAUSED", views.brief_status(conn))
        finally:
            conn.close()
