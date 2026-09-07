"""Exports preserve the chosen privacy boundary and one canonical point in time."""

from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest import mock
import zipfile

import swarmctl as s
from swarmkit import audit


class AuditSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-audit-safety-")
        self.root = Path(self.temp.name).resolve() / ".swarm"
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

    def test_runtime_symlinks_and_special_files_do_not_pull_unrelated_data_into_export(self):
        outside = self.root.parent / "unrelated"
        outside.mkdir()
        private = outside / "private.txt"
        private.write_text("unrelated-secret-marker")
        (self.root / "runs/file-link").symlink_to(private)
        (self.root / "runs/directory-link").symlink_to(outside, target_is_directory=True)
        os.mkfifo(self.root / "runs/live-pipe")
        (self.root / "runs/ordinary.log").write_text("Run output")
        audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            content = b"".join(archive.read(name) for name in archive.namelist())
            omitted = json.loads(archive.read("swarm-audit/runtime-export.json"))["skipped"]
            self.assertEqual(archive.read("swarm-audit/runs/ordinary.log"), b"Run output")
        self.assertNotIn(b"unrelated-secret-marker", content)
        self.assertEqual(
            {item["path"] for item in omitted},
            {"runs/file-link", "runs/directory-link", "runs/live-pipe"},
        )
        self.assertTrue(audit.verify_audit(self.output)["ok"])

    def test_runtime_file_disappearing_during_copy_is_omitted_and_explained(self):
        path = self.root / "runs/rotating.log"
        path.write_text("Rotating log")
        real_copy = audit.shutil.copy2

        def remove_before_copy(source, target, *args, **kwargs):
            if Path(source) == path:
                path.unlink()
            return real_copy(source, target, *args, **kwargs)

        with mock.patch.object(audit.shutil, "copy2", side_effect=remove_before_copy):
            audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            omitted = json.loads(archive.read("swarm-audit/runtime-export.json"))["skipped"]
        self.assertEqual(omitted[0]["path"], "runs/rotating.log")
        self.assertIn("disappeared", omitted[0]["reason"])

    def test_runtime_file_becoming_a_symlink_during_copy_is_not_followed(self):
        path = self.root / "runs/rotating.log"
        path.write_text("Run output")
        private = self.root.parent / "private.txt"
        private.write_text("private-race-marker")
        real_copy = audit.shutil.copy2

        def replace_before_copy(source, target, *args, **kwargs):
            if Path(source) == path:
                path.unlink()
                path.symlink_to(private)
            return real_copy(source, target, *args, **kwargs)

        with mock.patch.object(audit.shutil, "copy2", side_effect=replace_before_copy):
            audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertNotIn("swarm-audit/runs/rotating.log", archive.namelist())
            self.assertNotIn(
                b"private-race-marker", b"".join(archive.read(name) for name in archive.namelist())
            )
            omitted = json.loads(archive.read("swarm-audit/runtime-export.json"))["skipped"]
        self.assertEqual(omitted[0]["reason"], "became a symbolic link during copy")

    def test_intake_file_disappearing_during_copy_does_not_abort_canonical_export(self):
        case = self.case_with_payload()
        path = Path(case["payload_path"])
        real_copy = audit.shutil.copy2

        def remove_before_copy(source, target, *args, **kwargs):
            if Path(source) == path:
                path.unlink()
            return real_copy(source, target, *args, **kwargs)

        with mock.patch.object(audit.shutil, "copy2", side_effect=remove_before_copy):
            audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            omitted = json.loads(archive.read("swarm-audit/intake-export.json"))["skipped"]
            self.assertIn("swarm-audit/state.sqlite3", archive.namelist())
        self.assertEqual(omitted[0]["id"], case["id"])
        self.assertIn("disappeared", omitted[0]["reason"])
        self.assertTrue(audit.verify_audit(self.output)["ok"])

    def test_registered_artifact_disappearing_during_copy_is_reported(self):
        task = s.add_task(
            self.conn, "Inspect", "Inspect", "discovery", ["Checked"], [], 50, "manager", True
        )
        path = self.root.parent / "result.txt"
        path.write_text("Result")
        artifact = s.register_artifact(self.conn, task, path, actor="manager")
        self.conn.commit()
        real_copy = audit.shutil.copy2

        def remove_before_copy(source, target, *args, **kwargs):
            if Path(source) == path:
                path.unlink()
            return real_copy(source, target, *args, **kwargs)

        with mock.patch.object(audit.shutil, "copy2", side_effect=remove_before_copy):
            audit.export_audit(self.root, self.output, include_artifacts=True)
        with zipfile.ZipFile(self.output) as archive:
            omitted = json.loads(archive.read("swarm-audit/artifact-export.json"))["skipped"]
        self.assertEqual(omitted[0]["id"], artifact)
        self.assertIn("disappeared", omitted[0]["reason"])

    def test_unregistered_intake_payload_is_not_exported(self):
        payload = self.root / "intake/orphan.json"
        payload.write_text('{"private":"rolled-back request"}')
        audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertNotIn("swarm-audit/intake/orphan.json", archive.namelist())
        self.assertTrue(payload.exists())  # An audit does not clean the live workspace.

    def case_with_payload(self):
        source = self.root.parent / "intake-source.json"
        source.write_text('{"event":"original"}')
        return s.open_case(
            self.root,
            self.conn,
            "provider",
            "event-1",
            "Inspect",
            "Verify event",
            50,
            "ingress",
            ["Verified"],
            payload=source,
            ready=True,
        )

    def test_payload_changed_during_export_is_omitted_and_explained(self):
        case = self.case_with_payload()
        payload_path = Path(case["payload_path"])
        real_copy = audit.shutil.copy2

        def change_before_copy(source, target, *args, **kwargs):
            if Path(source) == payload_path:
                payload_path.write_text('{"event":"changed during export"}')
            return real_copy(source, target, *args, **kwargs)

        with mock.patch.object(audit.shutil, "copy2", side_effect=change_before_copy):
            audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            status = json.loads(archive.read("swarm-audit/intake-export.json"))
            payload_name = "swarm-audit/" + str(payload_path.relative_to(self.root))
            self.assertNotIn(payload_name, archive.namelist())
        self.assertEqual(status["copied"], [])
        self.assertEqual(
            status["skipped"],
            [{"id": case["id"], "entity_type": "case", "reason": "payload changed since intake"}],
        )
        self.assertTrue(audit.verify_audit(self.output)["ok"])
        self.assertTrue(payload_path.exists())

    def test_missing_payload_is_visible_in_export_manifest(self):
        case = self.case_with_payload()
        Path(case["payload_path"]).unlink()
        audit.export_audit(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            status = json.loads(archive.read("swarm-audit/intake-export.json"))
        self.assertEqual(status["skipped"][0]["reason"], "payload file is missing")
        self.assertEqual(status["skipped"][0]["id"], case["id"])

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
