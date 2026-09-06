#!/usr/bin/env python3
"""Run source and packaged release checks without network access."""

from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))

import package as package_script  # noqa: E402


def run(command, cwd):
    completed = subprocess.run(command, cwd=str(cwd), text=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def main():
    run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], PACKAGE_ROOT)
    run([sys.executable, "-B", "scripts/check_docs.py"], PACKAGE_ROOT)
    with tempfile.TemporaryDirectory(prefix="swarmkit-release-") as temporary:
        temporary_path = Path(temporary)
        archive = temporary_path / package_script.DEFAULT_OUTPUT.name
        run([sys.executable, "-B", "scripts/package.py", "--output", str(archive)], PACKAGE_ROOT)
        with zipfile.ZipFile(str(archive)) as bundle:
            bundle.extractall(str(temporary_path / "unpacked"))
        extracted = temporary_path / "unpacked" / "swarmkit"
        run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], extracted)
        run([sys.executable, "-B", "scripts/check_docs.py"], extracted)
    print("Release checks passed for %s." % package_script.DEFAULT_OUTPUT.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
