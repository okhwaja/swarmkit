"""Distribution builds contain source, never incidental local mission data."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from scripts import package


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-package-")
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        self.addCleanup(self.temp.cleanup)

    def write(self, relative, text="example"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_runtime_files_and_unrelated_root_files_are_excluded(self):
        self.write("README.md")
        for name in (
            ".swarm/runner.json",
            ".swarm/outbox/message.md",
            "scratch/private.json",
            "local-notes.md",
            ".env.json",
            "examples/demo-run/runner.json",
        ):
            path = self.write(name)
            if name.startswith("examples/demo-run/"):
                self.write("examples/demo-run/state.sqlite3")
            with mock.patch.object(package, "PACKAGE_ROOT", self.root):
                self.assertFalse(package.should_include(path), name)

    def test_symlinked_content_is_not_packaged(self):
        private = Path(self.temp.name) / "private.md"
        private.write_text("synthetic private content")
        (self.root / "docs").mkdir()
        linked = self.root / "docs" / "linked.md"
        linked.symlink_to(private)
        with mock.patch.object(package, "PACKAGE_ROOT", self.root):
            self.assertFalse(package.should_include(linked))

    def test_failed_build_preserves_the_previous_archive(self):
        self.write("README.md")
        output = Path(self.temp.name) / "release.zip"
        output.write_bytes(b"previous release")
        with (
            mock.patch.object(package, "PACKAGE_ROOT", self.root),
            mock.patch.object(
                package.shutil, "copyfileobj", side_effect=OSError("injected read failure")
            ),
        ):
            with self.assertRaisesRegex(OSError, "injected"):
                package.build_package(output)
        self.assertEqual(output.read_bytes(), b"previous release")
        self.assertEqual(list(output.parent.glob(".swarmkit-package-*")), [])

    def test_build_is_reproducible_and_does_not_include_runtime_tree(self):
        source = self.write("swarmkit/example.py", "VALUE = 1\n")
        self.write("README.md")
        self.write("bin/swarmctl", "#!/bin/sh\n")
        self.write("docs/guide.md")
        self.write(".swarm/runner.json", "must not ship")
        first, second = Path(self.temp.name) / "first.zip", Path(self.temp.name) / "second.zip"
        with mock.patch.object(package, "PACKAGE_ROOT", self.root):
            package.build_package(first)
            os.utime(source, (1700000000, 1700000000))
            package.build_package(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "swarmkit/swarmkit/example.py",
                    "swarmkit/README.md",
                    "swarmkit/bin/swarmctl",
                    "swarmkit/docs/guide.md",
                },
            )
            self.assertEqual(
                archive.getinfo("swarmkit/bin/swarmctl").external_attr >> 16 & 0o777, 0o755
            )


if __name__ == "__main__":
    unittest.main()
