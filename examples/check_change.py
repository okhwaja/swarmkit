#!/usr/bin/env python3
"""Reference bounded assessment of an already-authenticated provider observation.

No network or credentials. The harness owns observation provenance and action
permissions. Output is a next-action suggestion, never a merge authorization.
"""
import argparse
import json
from pathlib import Path


def assess(observation):
    fields = {
        "provider",
        "external_ref",
        "revision",
        "environment",
        "observed_at",
        "receipt",
        "review_approved",
        "comments_addressed",
        "ci_passed",
        "mergeable",
        "landed",
        "closed",
    }
    if not isinstance(observation, dict) or set(observation) != fields:
        raise ValueError("Missing or unknown provider observation fields")
    for key in (
        "review_approved",
        "comments_addressed",
        "ci_passed",
        "mergeable",
        "landed",
        "closed",
    ):
        if not isinstance(observation[key], bool):
            raise ValueError(key + " must be boolean")
    for key in fields - {
        "review_approved",
        "comments_addressed",
        "ci_passed",
        "mergeable",
        "landed",
        "closed",
    }:
        if not isinstance(observation[key], str) or not observation[key].strip():
            raise ValueError(key + " must be nonempty")
    if observation["landed"]:
        action, outcome = "verify-final-evidence", "satisfied"
    elif observation["closed"]:
        action, outcome = "request-manager-review", "rejected"
    elif not observation["comments_addressed"]:
        action, outcome = "address-comments", "pending"
    elif not observation["ci_passed"] or not observation["mergeable"]:
        action, outcome = "inspect-and-repair", "pending"
    elif not observation["review_approved"]:
        action, outcome = "wait-for-review", "pending"
    else:
        action, outcome = "check-current-grant-before-merge", "pending"
    terminal = {
        key: observation[key]
        for key in ("provider", "external_ref", "revision", "environment", "observed_at", "receipt")
    }
    terminal.update(check="change-landed", outcome=outcome)
    return {"next_action": action, "observation": terminal, "authorizes_merge": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observation")
    args = parser.parse_args()
    try:
        print(json.dumps(assess(json.loads(Path(args.observation).read_text())), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
