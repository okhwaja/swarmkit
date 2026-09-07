#!/usr/bin/env python3
"""Build a reproducible distribution from source directories, excluding local missions."""

import argparse
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = {"swarmkit", "docs", "guidance", "examples", "scripts", "tests"}
ROOT_FILES = {
    "swarmctl.py",
    "README.md",
    "AGENTS.md",
    "SETUP_AGENT.md",
    "CHANGELOG.md",
    ".gitignore",
    "pyproject.toml",
    "bin/swarmctl",
    ".github/workflows/ci.yml",
}
SOURCE_SUFFIXES = {".py", ".md", ".json", ".yml", ".yaml", ".toml"}
EXCLUDED_PARTS = {"__pycache__", "dist", ".pytest_cache", ".ruff_cache", "node_modules"}


def package_version():
    source = (PACKAGE_ROOT / "swarmkit" / "core.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION = "([^"]+)"$', source, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read VERSION from swarmkit/core.py")
    return match.group(1)


DEFAULT_OUTPUT = PACKAGE_ROOT / "dist" / ("swarmkit-%s.zip" % package_version())


def should_include(path):
    try:
        relative = path.relative_to(PACKAGE_ROOT)
    except ValueError:
        return False
    if not path.is_file() or path.is_symlink():
        return False
    parent = path.parent
    while parent != PACKAGE_ROOT:
        if parent.is_symlink() or (parent / "state.sqlite3").exists():
            return False
        parent = parent.parent
    if relative.as_posix() in ROOT_FILES:
        return True
    if relative.parts[0] not in SOURCE_DIRECTORIES:
        return False
    if any(part.startswith(".") or part in EXCLUDED_PARTS for part in relative.parts):
        return False
    return path.suffix in SOURCE_SUFFIXES


def package_files():
    for relative in sorted(ROOT_FILES):
        path = PACKAGE_ROOT / relative
        if should_include(path):
            yield path
    for name in sorted(SOURCE_DIRECTORIES):
        source = PACKAGE_ROOT / name
        if not source.is_dir() or source.is_symlink():
            continue
        for directory, children, filenames in os.walk(source, followlinks=False):
            folder = Path(directory)
            if (folder / "state.sqlite3").exists():
                children[:] = []
                continue
            # Pruning avoids traversing large mission/checkouts/cache trees at all.
            children[:] = sorted(
                child
                for child in children
                if not child.startswith(".")
                and child not in EXCLUDED_PARTS
                and not (folder / child).is_symlink()
            )
            for filename in sorted(filenames):
                path = folder / filename
                if should_include(path):
                    yield path


def build_package(output):
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".swarmkit-package-", dir=output.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in package_files():
                relative = path.relative_to(PACKAGE_ROOT)
                info = zipfile.ZipInfo(
                    (Path("swarmkit") / relative).as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
                )
                info.create_system = 3
                executable = relative.as_posix() in {"bin/swarmctl", "swarmctl.py"} or (
                    relative.parts[0] == "scripts" and path.suffix == ".py"
                )
                info.external_attr = (0o100755 if executable else 0o100644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as source, archive.open(info, "w") as destination:
                    shutil.copyfileobj(source, destination)
        os.replace(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    print(build_package(args.output))


if __name__ == "__main__":
    main()
