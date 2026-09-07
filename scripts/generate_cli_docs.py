#!/usr/bin/env python3
"""Generate the checked-in CLI reference directly from argparse."""

import argparse
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

import swarmctl  # noqa: E402


def subparser_action(parsed):
    return next(
        (action for action in parsed._actions if isinstance(action, argparse._SubParsersAction)),
        None,
    )


def render():
    sections = [
        "# CLI reference",
        "",
        "Generated from `swarmctl.py` for version `%s`. Do not edit by hand; run "
        "`python3 scripts/generate_cli_docs.py`." % swarmctl.VERSION,
        "",
    ]

    def visit(parsed, path):
        parsed.prog = "swarmctl" + (" " + " ".join(path) if path else "")
        title = "swarmctl" + (" " + " ".join(path) if path else "")
        sections.extend(
            ["## `%s`" % title, "", "```text", parsed.format_help().rstrip(), "```", ""]
        )
        action = subparser_action(parsed)
        if action:
            for name in sorted(action.choices):
                visit(action.choices[name], path + [name])

    visit(swarmctl.parser(), [])
    return "\n".join(sections).rstrip() + "\n"


def main():
    output = PACKAGE_ROOT / "docs" / "CLI_REFERENCE.md"
    output.write_text(render(), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
