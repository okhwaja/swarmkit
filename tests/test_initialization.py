"""A failed or concurrent first run must not poison an existing workspace."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from swarmkit import setup
from swarmkit.core import SwarmError, process_lock
from swarmkit.storage import connect, mission


class InitializationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-init-")
        self.root = Path(self.temp.name) / ".swarm"

    def tearDown(self):
        self.temp.cleanup()

    def initialize(self):
        return setup.initialize(self.root, "Restore delivery", ["Records arrive"], [])

    def test_failed_schema_creation_can_be_retried(self):
        with mock.patch.object(setup, "execute_schema", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.initialize()
        self.assertFalse((self.root / "state.sqlite3").exists())
        mission_id = self.initialize()
        conn = connect(self.root)
        try:
            self.assertEqual(mission(conn)["id"], mission_id)
        finally:
            conn.close()

    def test_failed_initial_event_leaves_no_published_database(self):
        with mock.patch.object(setup, "add_event", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.initialize()
        self.assertFalse((self.root / "state.sqlite3").exists())
        self.initialize()

    def test_existing_runner_configuration_is_preserved(self):
        self.root.mkdir()
        config = {
            "command": ["internal-agent", "{prompt_file}"],
            "workspace": {"provider": "manual"},
        }
        path = self.root / "runner.json"
        original = json.dumps(config)
        path.write_text(original)
        self.initialize()
        self.assertEqual(path.read_text(), original)

    def test_concurrent_initializer_cannot_publish(self):
        with process_lock(self.root / ".init.lock"):
            with self.assertRaisesRegex(SwarmError, "Another process"):
                self.initialize()
        self.assertFalse((self.root / "state.sqlite3").exists())
        self.initialize()

    def test_second_initialize_preserves_original_mission(self):
        mission_id = self.initialize()
        with self.assertRaisesRegex(SwarmError, "already exists"):
            self.initialize()
        conn = connect(self.root)
        try:
            self.assertEqual(mission(conn)["id"], mission_id)
        finally:
            conn.close()

    def test_empty_objective_is_rejected_before_creating_workspace(self):
        with self.assertRaises(SwarmError):
            setup.initialize(self.root, " \n", [], [])
        self.assertFalse(self.root.exists())
