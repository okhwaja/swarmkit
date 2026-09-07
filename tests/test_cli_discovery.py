"""An installed CLI remains discoverable and safe outside its package directory."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from swarmkit import cli, installation
from swarmkit.cli_help import GUIDES
from swarmkit.core import PACKAGE_ROOT, SwarmError, VERSION


class CliDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-cli-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin_dir = self.directory / "bin ' with spaces $literal"
        self.work = self.directory / "unrelated work"
        self.work.mkdir()
        self.root = self.work / "mission state"
        self.env = dict(os.environ, SWARM_ROOT=str(self.root), PYTHONDONTWRITEBYTECODE="1")

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(PACKAGE_ROOT / "swarmctl.py"), *args],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def installed(self, *args, env=None):
        return subprocess.run(
            [str(self.bin_dir / "swarmctl"), *args],
            cwd=self.work,
            env=env or self.env,
            capture_output=True,
            text=True,
        )

    def test_bundled_executable_bootstraps_installation(self):
        result = subprocess.run(
            [str(PACKAGE_ROOT / "bin/swarmctl"), "install", "--bin-dir", str(self.bin_dir)],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.installed("--version").stdout.strip(), VERSION)

    def test_install_and_use_from_unrelated_directory_without_python_on_path(self):
        result = self.run_cli("install", "--bin-dir", str(self.bin_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        env = dict(self.env, PATH=str(self.bin_dir))
        # The launcher pins the installing interpreter rather than looking for
        # python3 in the agent's potentially different PATH.
        result = subprocess.run(
            ["swarmctl", "--version"], cwd=self.work, env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), VERSION)
        result = self.installed("guide", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (PACKAGE_ROOT / "docs/AGENT_GUIDE.md").read_text())
        self.assertFalse(self.root.exists())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_installed_cli_round_trip_preserves_explicit_root_across_directories(self):
        installation.install_launcher(self.bin_dir)
        root = self.directory / "chosen mission"
        result = self.installed(
            "--root",
            str(root),
            "init",
            "--objective",
            "Diagnose latency",
            "--success",
            "Cite measurements",
            "--constraint",
            "Keep changes local",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.installed("--root", str(root), "ask", "--question", "What should we measure?")
        self.assertEqual(result.returncode, 0, result.stderr)
        task_id = json.loads(result.stdout)["inquiry_task_id"]
        result = self.installed("--root", str(root), "task", "show", task_id)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["id"], task_id)
        result = self.installed("--root", str(root), "report")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(result.stdout.strip()).is_file())
        self.assertFalse(self.root.exists())
        self.assertFalse((self.work / ".swarm").exists())

    def test_launcher_quotes_package_and_interpreter_paths(self):
        special = self.directory / "package ' $literal `literal`"
        special.mkdir()
        script = special / "entry.py"
        script.write_text("import sys\nprint(repr(sys.argv[1:]))\n")
        interpreter = special / "python with spaces"
        interpreter.symlink_to(sys.executable)
        with (
            mock.patch.object(installation, "CLI_PATH", script),
            mock.patch.object(installation.sys, "executable", str(interpreter)),
        ):
            installation.install_launcher(self.bin_dir)
        args = ["a b", "'quoted'", "$literal", "`literal`", "line\nbreak"]
        result = self.installed(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), repr(args))
        self.assertEqual(
            sorted(p.name for p in special.iterdir()), ["entry.py", "python with spaces"]
        )

    def test_concurrent_identical_installations_publish_one_complete_launcher(self):
        command = [
            sys.executable,
            "-B",
            str(PACKAGE_ROOT / "swarmctl.py"),
            "install",
            "--bin-dir",
            str(self.bin_dir),
        ]
        processes = [
            subprocess.Popen(
                command,
                cwd=self.work,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(3)
        ]
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual([p.name for p in self.bin_dir.iterdir()], ["swarmctl"])
        self.assertEqual(self.installed("--version").stdout.strip(), VERSION)

    def test_install_preserves_existing_command_and_symlink_target(self):
        self.bin_dir.mkdir()
        command = self.bin_dir / "swarmctl"
        command.write_text("existing tool")
        with self.assertRaisesRegex(SwarmError, "Refusing to replace"):
            installation.install_launcher(self.bin_dir)
        self.assertEqual(command.read_text(), "existing tool")
        command.unlink()
        target = self.directory / "another command"
        target.write_text("keep this")
        command.symlink_to(target)
        with self.assertRaisesRegex(SwarmError, "Refusing to replace"):
            installation.install_launcher(self.bin_dir)
        self.assertTrue(command.is_symlink())
        self.assertEqual(target.read_text(), "keep this")
        target.unlink()
        with self.assertRaisesRegex(SwarmError, "Refusing to replace"):
            installation.install_launcher(self.bin_dir)
        self.assertTrue(command.is_symlink())
        self.assertFalse(target.exists())

    def test_failed_publication_leaves_no_partial_launcher(self):
        with mock.patch.object(installation.os, "link", side_effect=OSError("injected failure")):
            with self.assertRaisesRegex(OSError, "injected failure"):
                installation.install_launcher(self.bin_dir)
        self.assertEqual(list(self.bin_dir.iterdir()), [])

    def test_guides_and_help_never_open_mission_state(self):
        commands = [[], ["--help"], ["help"], ["help", "decision", "resolve"]]
        commands += [["guide", topic] for topic in GUIDES]
        with mock.patch.object(cli, "root_path", side_effect=AssertionError("accessed mission")):
            for command in commands:
                with (
                    self.subTest(command=command),
                    contextlib.redirect_stdout(io.StringIO()) as out,
                ):
                    if command == ["--help"]:
                        with self.assertRaises(SystemExit) as exit_info:
                            cli.main(command)
                        self.assertEqual(exit_info.exception.code, 0)
                    else:
                        self.assertEqual(cli.main(command), 0)
                    self.assertTrue(out.getvalue().strip())
        self.assertFalse(self.root.exists())

    def test_nested_help_matches_flag_help_and_rejects_unknown_paths(self):
        direct = self.run_cli("decision", "resolve", "--help")
        topic = self.run_cli("help", "decision", "resolve")
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(topic.returncode, 0, topic.stderr)
        self.assertEqual(direct.stdout, topic.stdout)
        self.assertTrue(direct.stdout.startswith("usage: swarmctl decision resolve "))
        for args in [("help", "missing"), ("help", "ask", "missing"), ("guide", "missing")]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.root.exists())
