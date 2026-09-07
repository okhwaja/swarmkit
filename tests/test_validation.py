"""Malformed user input fails with actionable domain errors, before any mutation."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest import mock

import swarmctl as s
from swarmkit import config, delivery, policies, runtime, workspaces


class ValidationTest(unittest.TestCase):
    def test_invalid_runner_fails_setup_and_scheduler_before_allocating_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".swarm"
            s.initialize(root, "Mission", ["Verified"], [])
            path = root / "runner.json"
            original = json.loads(path.read_text())
            original["command"] = [sys.executable, "adapter.py", "{prompt_file}"]
            for change in [
                {"command": [sys.executable, "{prompt_file}", "{typo}"]},
                {"command": [sys.executable, "{prompt_file[0]}"]},
                {"command": [sys.executable, "{prompt_file!r}"]},
                {"command": [sys.executable, "{prompt_file:>100}"]},
                {"command": [sys.executable, "{prompt_file}", "broken {"]},
                {"command": [sys.executable, "{prompt_file}", "nul\0value"]},
                {"scheduler_poll_seconds": float("nan")},
                {"manager_review_debounce_seconds": float("inf")},
                {"models": {"manager": []}},
                {"escalation_models": {"worker": 42}},
            ]:
                with self.subTest(change=change):
                    path.write_text(json.dumps(dict(original, **change)))
                    self.assertFalse(s.setup_check(root)["ok"])
                    with mock.patch.object(runtime, "dispatch") as dispatch:
                        with self.assertRaises(s.SwarmError):
                            s.run_loop(root, 1)
                        dispatch.assert_not_called()
                    conn = s.connect(root)
                    try:
                        for table in ("attempts", "agent_runs", "manager_reviews"):
                            self.assertEqual(
                                conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0
                            )
                    finally:
                        conn.close()

    def test_templates_preserve_argv_boundaries_and_literal_braces(self):
        rendered = config.render_command(
            ["adapter", "--path={path}", '{{"key":"literal"}}'],
            {"path": "/checkout with spaces/$(literal);file"},
            "Test command",
        )
        self.assertEqual(
            rendered,
            ["adapter", "--path=/checkout with spaces/$(literal);file", '{"key":"literal"}'],
        )
        with self.assertRaises(s.SwarmError):
            config.render_command(["adapter", "{path}"], {"path": "bad\0path"}, "Test command")

    def test_adapter_templates_are_checked_when_configured(self):
        source = Path(s.__file__).parent / "examples/extensions/harness-email/extension.json"
        manifest = json.loads(source.read_text())
        manifest["executor"] = {
            "type": "command",
            "command": ["adapter", "{envelope_file}", "{typo}"],
        }
        with self.assertRaises(s.SwarmError):
            delivery.validate_extension_manifest(manifest)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runner.json").write_text(
                json.dumps({"workspace": {"provider": "command", "command": ["adapter", "{typo}"]}})
            )
            with self.assertRaises(s.SwarmError):
                workspaces.workspace_config(root)

    def test_policy_rejects_malformed_stage_values_without_tracebacks(self):
        source = (
            Path(s.__file__).parent / "examples/policy-packs/performance-investigation/policy.json"
        )
        original = json.loads(source.read_text())
        invalid = [
            ("kind", []),
            ("depends_on", [{}]),
            ("fresh_session_from", [{}]),
            ("title", "{goal.missing}"),
            ("title", "{goal[200]}"),
        ]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                manifest = copy.deepcopy(original)
                manifest["stages"][0][key] = value
                with self.assertRaises(s.SwarmError):
                    policies.validate_policy_manifest(manifest)

    def test_extension_rejects_non_string_executor_type(self):
        source = Path(s.__file__).parent / "examples/extensions/harness-email/extension.json"
        manifest = json.loads(source.read_text())
        manifest["executor"]["type"] = []
        with self.assertRaises(s.SwarmError):
            delivery.validate_extension_manifest(manifest)

    def test_workspace_rejects_non_string_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runner.json").write_text(json.dumps({"workspace": {"provider": []}}))
            with self.assertRaises(s.SwarmError):
                workspaces.workspace_config(root)

    def test_task_rejects_empty_goal_or_criteria_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".swarm"
            s.initialize(root, "Mission", ["Verified"], [])
            conn = s.connect(root)
            try:
                for title, description, acceptance in [
                    (" ", "Inspect", ["Checked"]),
                    ("Inspect", " ", ["Checked"]),
                    ("Inspect", "Inspect", []),
                    ("Inspect", "Inspect", [" "]),
                ]:
                    with self.subTest(title=title, acceptance=acceptance):
                        with self.assertRaises(s.SwarmError):
                            s.add_task(
                                conn,
                                title,
                                description,
                                "discovery",
                                acceptance,
                                [],
                                50,
                                "manager",
                                True,
                            )
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
            finally:
                conn.close()
