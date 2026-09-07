"""Exports preserve the chosen privacy boundary and one canonical point in time."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock
import zipfile

import swarmctl as s
from swarmkit import audit


class AuditSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-audit-safety-")
        self.root = Path(self.temp.name) / ".swarm"
        self.output = Path(self.temp.name) / "audit.zip"
        s.initialize(self.root, "Private objective", ["Verified"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def test_share_safe_never_reads_or_copies_private_runtime_files(self):
        (self.root / "runs/private.txt").write_text("private-content")
        with mock.patch.object(
            audit.shutil, "copytree", side_effect=AssertionError("private copy")
        ):
            with mock.patch.object(
                audit, "mission_snapshot", side_effect=AssertionError("private snapshot")
            ):
                audit.export_audit(self.root, self.output, share_safe=True)
        with zipfile.ZipFile(self.output) as archive:
            content = b"".join(archive.read(name) for name in archive.namelist())
        self.assertNotIn(b"Private objective", content)
        self.assertNotIn(b"private-content", content)
        self.assertTrue(audit.verify_audit(self.output)["ok"])

    def test_failed_export_preserves_previous_output(self):
        self.output.write_bytes(b"previous accepted export")
        with mock.patch.object(audit, "explain_state", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                audit.export_audit(self.root, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous accepted export")

    def test_export_does_not_reconcile_expired_work_only_in_its_copy(self):
        task = s.add_task(
            self.conn, "Inspect", "Inspect", "discovery", ["Checked"], [], 50, "manager", True
        )
        s.claim_task(self.conn, task, "worker", 60)
        self.conn.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (task,))
        self.conn.commit()
        watermark = self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0]
        audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            snapshot = json.loads(archive.read("swarm-audit/snapshot.json"))
            manifest = json.loads(archive.read("swarm-audit/manifest.json"))
        self.assertEqual(snapshot["tasks"][0]["status"], "CLAIMED")
        self.assertEqual(manifest["event_watermark"], watermark)
        self.assertEqual(self.conn.execute("SELECT MAX(seq) FROM events").fetchone()[0], watermark)

    def test_export_streams_files_without_reading_a_zip_back_into_memory(self):
        (self.root / "runs/large.log").write_bytes(b"log line\n" * 100000)
        with mock.patch.object(
            zipfile.ZipFile, "read", side_effect=AssertionError("whole archive read")
        ):
            audit.export_audit(self.root, self.output)
        self.assertTrue(audit.verify_audit(self.output)["ok"])

    def test_malformed_manifest_returns_problems_instead_of_crashing(self):
        for manifest in (
            {"files": [None]},
            {"files": "bad"},
            [],
            {"files": [{"path": "../escape", "size_bytes": 0, "sha256": ""}]},
        ):
            with zipfile.ZipFile(self.output, "w") as archive:
                if isinstance(manifest, dict):
                    manifest["format_version"] = 1
                archive.writestr("swarm-audit/manifest.json", json.dumps(manifest))
            self.assertFalse(audit.verify_audit(self.output)["ok"])
