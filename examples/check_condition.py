#!/usr/bin/env python3
"""Read a trusted provider observation and check one exact revision-bound predicate.

The harness obtains the observation through its provider integration. This example
has no network or mutation capability and never evaluates code from the receipt.
"""

import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observation", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--field", required=True)
    parser.add_argument("--equals", required=True, help="Expected JSON value")
    args = parser.parse_args()
    try:
        observation = json.loads(args.observation.read_text(encoding="utf-8"))
        expected = json.loads(args.equals)
        passed = (
            observation["revision"] == args.revision
            and observation["environment"] == args.environment
            and args.field in observation["values"]
            and json.dumps(observation["values"][args.field], sort_keys=True)
            == json.dumps(expected, sort_keys=True)
        )
        print(
            json.dumps(
                {
                    "passed": passed,
                    "revision": args.revision,
                    "environment": args.environment,
                    "field": args.field,
                    "observed_at": observation["observed_at"],
                }
            )
        )
        return 0 if passed else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"passed": False, "error": str(error)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
