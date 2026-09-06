from pathlib import Path
import subprocess
import sys
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class DocumentationTest(unittest.TestCase):
    def test_documentation_contract(self):
        completed = subprocess.run(
            [sys.executable, "-B", str(PACKAGE_ROOT / "scripts" / "check_docs.py")],
            cwd=str(PACKAGE_ROOT), text=True, capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
