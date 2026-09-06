#!/usr/bin/env python3
"""Build a portable Swarmkit ZIP containing code, guidance, docs, examples, and tests."""

import argparse
from pathlib import Path
import re
import zipfile


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {"__pycache__", "dist", ".pytest_cache"}


def package_version():
    source = (PACKAGE_ROOT / "swarmctl.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION = "([^"]+)"$', source, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read VERSION from swarmctl.py")
    return match.group(1)


DEFAULT_OUTPUT = PACKAGE_ROOT / "dist" / ("swarmkit-%s.zip" % package_version())


def should_include(path):
    relative = path.relative_to(PACKAGE_ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    return path.is_file() and path.suffix in {".py", ".md", ".json", ".yml", ".yaml"} or relative == Path("bin/swarmctl")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(output), "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE_ROOT.rglob("*")):
            if not should_include(path):
                continue
            target = Path("swarmkit") / path.relative_to(PACKAGE_ROOT)
            info = zipfile.ZipInfo.from_file(str(path), str(target))
            if path.name == "swarmctl" or path.suffix == ".py":
                info.external_attr = (0o755 & 0xFFFF) << 16
            with path.open("rb") as source:
                archive.writestr(info, source.read(), compress_type=zipfile.ZIP_DEFLATED)
    print(output)


if __name__ == "__main__":
    main()
