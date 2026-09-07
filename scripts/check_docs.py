#!/usr/bin/env python3
"""Check documentation, public commands, versions, links, and bundled extensions."""

import argparse
import json
from pathlib import Path
import re
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

import swarmctl  # noqa: E402
import package as package_script  # noqa: E402
import generate_cli_docs  # noqa: E402


REQUIRED_DOCUMENTS = [
    "AGENTS.md",
    "docs/RUNTIME_SAFETY.md",
    "docs/ROADMAP_BACKLOG.md",
    "README.md",
    "SETUP_AGENT.md",
    "CHANGELOG.md",
    "docs/DOCUMENTATION_POLICY.md",
    "docs/EXTENSIONS.md",
    "docs/CLI_REFERENCE.md",
    "docs/HARNESS_INTEGRATION.md",
    "docs/MODEL_GUIDANCE.md",
    "docs/POLICY_PACKS.md",
    "docs/PERSISTENT_SERVICES.md",
    "docs/RESPONSIVE_ORCHESTRATION.md",
    "docs/RESPONSIVE_ORCHESTRATION_PRODUCT_SPEC.md",
    "docs/SYSTEM_EXPLAINER.md",
    "docs/USER_MANUAL.md",
    "docs/AGENT_GUIDE.md",
]

REQUIRED_GUIDANCE = [
    "HARNESS_SYSTEM_PROMPT.md",
    "manager.md",
    "worker.md",
    "verifier.md",
    "briefer.md",
    "liaison.md",
    "status.md",
]


def root_commands():
    parsed = swarmctl.parser()
    action = next(item for item in parsed._actions if isinstance(item, argparse._SubParsersAction))
    return set(action.choices)


def check_internal_links(markdown_path):
    errors = []
    text = markdown_path.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = target.strip().strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        file_target = target.split("#", 1)[0]
        if not file_target:
            continue
        resolved = (markdown_path.parent / file_target).resolve()
        if not resolved.exists():
            errors.append(
                "%s has broken link: %s" % (markdown_path.relative_to(PACKAGE_ROOT), target)
            )
    return errors


def run_checks():
    errors = []
    for relative in REQUIRED_DOCUMENTS:
        if not (PACKAGE_ROOT / relative).is_file():
            errors.append("Missing required document: %s" % relative)
    for name in REQUIRED_GUIDANCE:
        path = PACKAGE_ROOT / "guidance" / name
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            errors.append("Missing or empty role guidance: %s" % name)
    # Check shipped documentation, not private Markdown in a local mission.
    for path in package_script.package_files():
        if path.suffix == ".md":
            errors.extend(check_internal_links(path))

    if package_script.package_version() != swarmctl.VERSION:
        errors.append("Package version does not match swarmctl VERSION")
    expected_name = "swarmkit-%s.zip" % swarmctl.VERSION
    if package_script.DEFAULT_OUTPUT.name != expected_name:
        errors.append("Default package filename must be %s" % expected_name)
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    if expected_name not in readme:
        errors.append("README must name current package %s" % expected_name)
    cli_reference = PACKAGE_ROOT / "docs" / "CLI_REFERENCE.md"
    if (
        cli_reference.is_file()
        and cli_reference.read_text(encoding="utf-8") != generate_cli_docs.render()
    ):
        errors.append("CLI reference is stale; run python3 scripts/generate_cli_docs.py")

    commands = root_commands()
    for command in {
        "policy",
        "case",
        "extension",
        "delivery",
        "finding",
        "wait",
        "setup-check",
        "run",
        "report",
        "export",
    }:
        if command not in commands:
            errors.append("Missing documented root command: %s" % command)

    pack_root = PACKAGE_ROOT / "examples" / "policy-packs"
    manifests = sorted(pack_root.glob("*/policy.json"))
    if not manifests:
        errors.append("No example policy packs found")
    for manifest_path in manifests:
        try:
            manifest, guidance, _ = swarmctl.read_policy_source(manifest_path.parent)
            json.dumps(manifest)
            if not guidance.strip():
                errors.append("Empty policy guidance: %s" % manifest_path.parent)
        except (swarmctl.SwarmError, OSError, ValueError) as exc:
            errors.append("Invalid policy pack %s: %s" % (manifest_path.parent, exc))
    extension_root = PACKAGE_ROOT / "examples" / "extensions"
    extension_manifests = sorted(extension_root.glob("*/extension.json"))
    if not extension_manifests:
        errors.append("No example delivery extensions found")
    for manifest_path in extension_manifests:
        try:
            manifest, guidance, _ = swarmctl.read_extension_source(manifest_path.parent)
            json.dumps(manifest)
            if not guidance.strip():
                errors.append("Empty extension guidance: %s" % manifest_path.parent)
        except (swarmctl.SwarmError, OSError, ValueError) as exc:
            errors.append("Invalid delivery extension %s: %s" % (manifest_path.parent, exc))
    return errors


def main():
    errors = run_checks()
    if errors:
        for error in errors:
            print("ERROR: %s" % error, file=sys.stderr)
        return 2
    print("Documentation checks passed for Swarmkit %s." % swarmctl.VERSION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
