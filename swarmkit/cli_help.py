"""Offline discovery for people and agents, using the same parser and shipped guides."""

import argparse

from .core import PACKAGE_ROOT


GUIDES = {
    "agent": ("Operate Swarmkit on a user's behalf", "docs/AGENT_GUIDE.md"),
    "user": ("Direct a mission and review its results", "docs/USER_MANUAL.md"),
    "setup": ("Connect and verify an agent harness", "SETUP_AGENT.md"),
    "harness": ("Integrate tools, permissions, and fresh sessions", "docs/HARNESS_INTEGRATION.md"),
    "runtime": ("Recover, pause, amend, and inspect evidence", "docs/RUNTIME_SAFETY.md"),
    "workflows": ("Install and apply reusable policies", "docs/POLICY_PACKS.md"),
    "services": ("Operate standing services and cases", "docs/PERSISTENT_SERVICES.md"),
    "delivery": ("Configure report delivery", "docs/EXTENSIONS.md"),
}

# Each entry explains effects and next steps that argument names alone cannot convey.
COMMAND_GUIDANCE = {
    "init": (
        "Create a new mission from its outcome, success criteria, and boundaries. "
        "This creates local state; it does not launch agents or configure their harness.",
        "Example: swarmctl --root /work/run/.swarm init --objective 'Diagnose slow requests' "
        "--success 'Evidence identifies the bottleneck' --constraint 'Keep changes local'\n"
        "Next: swarmctl guide setup, then setup-check and run --max-cycles 20.",
    ),
    "ask": (
        "Create a briefing task to explain recorded work. This writes an inquiry to the "
        "mission; it does not answer immediately, change the goal, or grant permission. "
        "A completed or cancelled mission cannot accept new inquiries.",
        "Example: swarmctl ask --question 'What is blocking progress, and what evidence explains it?'\n"
        "Next: if no controller is active, run swarmctl run --max-cycles 5; then "
        "swarmctl task show TASK_ID to read the result and artifact paths. "
        "A paused mission must resume before the briefing can run.",
    ),
    "status": (
        "Print mission state as JSON, or a concise human update with --brief. "
        "Inspect the recorded outcome; a stopped controller does not imply success.",
        "Example: swarmctl status --brief\nNext: swarmctl report for workstreams, "
        "or swarmctl why for blockers and recovery needs.",
    ),
    "report": (
        "Refresh the human progress report and print its local Markdown path. "
        "It describes major workstreams, evidence, forecasts, and needs from the user.",
        "Example: swarmctl report\nNext: open the printed file; use decision show ID "
        "for a question needing an answer. This command does not send the report.",
    ),
    "run": (
        "Launch configured manager and worker harnesses for a bounded number of cycles. "
        "It can stop for a decision, external wait, recovery, no ready work, or its cycle limit.",
        "Example: swarmctl run --max-cycles 20\nNext: swarmctl status --brief. "
        "For ongoing scheduled checks, see swarmctl serve --help and swarmctl guide runtime.",
    ),
    "serve": (
        "Keep a controller running to handle work and future checks. This launches configured "
        "harnesses; it does not install an OS service.",
        "Read swarmctl guide runtime before configuring unattended operation.",
    ),
    "decision resolve": (
        "Record the user's answer to an open decision. Include --choice when selecting an "
        "offered option; copy its exact value. Do not invent authorization on the user's behalf.",
        "First: swarmctl decision show DECISION_ID\n"
        "Example: swarmctl decision resolve DECISION_ID --answer 'Keep all changes local'\n"
        "Next: start another bounded run if execution stopped waiting. A separate mission "
        "pause still requires resume. A refusal must be honored.",
    ),
    "decision revise": (
        "Correct an existing answer while preserving its history and notifying affected work. "
        "Supply --choice again when choosing an offered option.",
        "Example: swarmctl decision revise DECISION_ID --answer 'Limit the repair window to ten minutes'",
    ),
    "pause": (
        "Stop new claims and prevent active attempts from recording further task progress. "
        "Running processes and submitted external actions may continue.",
        "Example: swarmctl pause --reason 'Review a change in scope'\n"
        "Next: recover and why. Resolve unfinished activity before resume or amend. "
        "Use drain to let current work finish first.",
    ),
    "drain": (
        "Stop new claims, let current activity finish, then pause. "
        "Unfinished or uncertain external activity can keep the drain pending.",
        "Example: swarmctl drain --reason 'Pause after current work finishes'\n"
        "Next: status --brief; use recover and why if the drain remains pending.",
    ),
    "resume": (
        "Allow a paused mission to work again after unfinished runs and uncertain actions "
        "have been resolved. This does not itself start a controller.",
        "Example: swarmctl resume --reason 'Continue the agreed plan'\n"
        "Next: run --max-cycles 20 if no controller is active.",
    ),
    "cancel": (
        "Permanently cancel remaining mission work and preserve history. "
        "This cannot be resumed, does not kill processes, and does not undo external actions.",
        "Example: swarmctl cancel --reason 'The objective is no longer needed'\n"
        "Next: inspect recover and why for outstanding activity.",
    ),
    "amend": (
        "Replace the complete objective, success criteria, and constraints of a paused, "
        "quiescent mission. Omitted criteria and constraints are removed. "
        "The manager must reconsider unfinished work.",
        "First: pause, recover, and resolve reported uncertainty.\n"
        "Example: swarmctl amend --objective 'Diagnose only' --success 'Cite evidence' "
        "--constraint 'Do not change production' --reason 'Separate diagnosis from repair'\n"
        "Next: resume, then run. See swarmctl guide runtime.",
    ),
    "export": (
        "Write a local audit ZIP. Full exports may contain confidential prompts, outputs, "
        "and data. --share-safe exports structural telemetry only, not a redacted full report.",
        "Example: swarmctl export --output /work/exports/run.zip --include-artifacts\n"
        "Choose an output outside mission state. Review REVIEW_ME.md and omission reports "
        "inside the archive before sharing. Export does not send or publish anything.",
    ),
}


class WorkflowHelpFormatter(argparse.HelpFormatter):
    """Wrap prose while retaining separate example and next-action lines."""

    def _fill_text(self, text, width, indent):
        return "\n".join(
            super(WorkflowHelpFormatter, self)._fill_text(line, width, indent)
            for line in text.splitlines()
        )


def subcommands(parsed):
    action = next(
        (item for item in parsed._actions if isinstance(item, argparse._SubParsersAction)), None
    )
    return action.choices if action else {}


def describe_commands(parsed, path=()):
    guidance = COMMAND_GUIDANCE.get(" ".join(path))
    if guidance:
        parsed.description, parsed.epilog = guidance
        parsed.formatter_class = WorkflowHelpFormatter
    for name, child in subcommands(parsed).items():
        describe_commands(child, path + (name,))


def show_command_help(parsed, path):
    for name in path:
        choices = subcommands(parsed)
        if name not in choices:
            parsed.error("unknown help topic %r; choose from: %s" % (name, ", ".join(choices)))
        parsed = choices[name]
    parsed.print_help()


def read_guide(topic):
    return (PACKAGE_ROOT / GUIDES[topic][1]).read_text(encoding="utf-8")
