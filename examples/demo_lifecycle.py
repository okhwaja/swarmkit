#!/usr/bin/env python3
"""Create a complete synthetic run and audit ZIP without invoking an AI harness."""

import argparse
from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from swarmkit.demo import run_demo  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="New .swarm directory")
    parser.add_argument("--output", required=True, help="Audit ZIP to create")
    args = parser.parse_args()
    print(
        run_demo(Path(args.root).expanduser().resolve(), Path(args.output).expanduser().resolve())
    )


if __name__ == "__main__":
    main()
