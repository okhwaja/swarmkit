"""Malformed user input fails with actionable domain errors, before any mutation."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import swarmctl as s
from swarmkit import delivery, policies, workspaces


class ValidationTest(unittest.TestCase):
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
