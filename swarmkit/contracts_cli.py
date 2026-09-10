"""CLI for structured decision mode and task-independent delivery commitments."""

from pathlib import Path
from .core import json_load, print_json, read_snapshot
from .storage import connect
from . import commitments as c
from .decision_briefs import configure_briefs, brief_mode


def add_contracts_cli(sub):
    mode = sub.add_parser(
        "decision-contract", help="Inspect/set structured human decision requirements"
    )
    mode.add_argument("--mode", choices=["legacy", "required"])
    mode.add_argument("--actor", default="human")
    group = sub.add_parser("commitment", help="Track delivery obligations independently of tasks")
    commands = group.add_subparsers(dest="commitment_command", required=True)
    create = commands.add_parser(
        "add", help="Record a required producer handoff and delivery scope atomically"
    )
    create.add_argument("--specification", required=True, help="JSON specification file")
    create.add_argument("--idempotency-key", required=True)
    create.add_argument("--actor", default="manager")
    listing = commands.add_parser("list")
    listing.add_argument("--task")
    for name in ("show", "bind", "observe", "wait", "signal", "adopt", "cancel"):
        parser = commands.add_parser(name)
        parser.add_argument("commitment_id")
        if name in {"bind", "observe", "wait", "adopt", "cancel"}:
            parser.add_argument("--expected-version", type=int, required=True)
        if name in {"bind", "observe", "wait"}:
            parser.add_argument("--task", required=True)
            parser.add_argument("--agent", required=True)
        if name in {"bind", "observe", "wait", "adopt"}:
            parser.add_argument("--idempotency-key", required=True)
        if name in {"signal", "adopt", "cancel"}:
            parser.add_argument("--actor", required=True)
        if name == "bind":
            parser.add_argument("--external-ref", required=True)
            parser.add_argument("--revision", required=True)
        elif name == "observe":
            parser.add_argument(
                "--observation", required=True, help="Trusted provider observation JSON file"
            )
        elif name == "wait":
            parser.add_argument("--next-check-at")
            parser.add_argument("--deadline", required=True)
            parser.add_argument("--signal-expected", action="store_true")
        elif name == "signal":
            parser.add_argument("--source", required=True)
            parser.add_argument("--external-id", required=True)
            parser.add_argument("--external-ref", required=True)
            parser.add_argument("--note", default="")
        elif name == "adopt":
            parser.add_argument("--followup-task", required=True)
            parser.add_argument("--reason", required=True)
        elif name == "cancel":
            parser.add_argument("--reason", required=True)


def handle_contracts_cli(root, args):
    if args.command not in {"commitment", "decision-contract"}:
        return False
    conn = connect(root)
    try:
        if args.command == "decision-contract":
            result = (
                configure_briefs(conn, args.mode, args.actor)
                if args.mode
                else {"decision_briefs": brief_mode(conn)}
            )
        else:
            cmd = args.commitment_command
            if cmd in {"list", "show"}:
                from .coordination import reconcile_conn

                reconcile_conn(conn)
                with read_snapshot(conn):
                    if cmd == "list":
                        result = c.list_commitments(conn, args.task)
                    else:
                        result = c.commitment_dict(conn, c.row_for(conn, args.commitment_id))
                        result["records"] = [
                            dict(row)
                            for row in conn.execute(
                                "SELECT * FROM commitment_records WHERE commitment_id=? ORDER BY rowid",
                                (args.commitment_id,),
                            )
                        ]
                        for row in result["records"]:
                            row["payload"] = json_load(row.pop("payload_json"))
            elif cmd == "add":
                result = c.create_commitment(
                    conn,
                    json_load(Path(args.specification).read_text()),
                    args.actor,
                    args.idempotency_key,
                )
            elif cmd == "bind":
                result = c.bind_commitment(
                    conn,
                    args.commitment_id,
                    args.task,
                    args.agent,
                    args.expected_version,
                    args.external_ref,
                    args.revision,
                    args.idempotency_key,
                )
            elif cmd == "observe":
                result = c.observe_commitment(
                    conn,
                    args.commitment_id,
                    args.task,
                    args.agent,
                    args.expected_version,
                    json_load(Path(args.observation).read_text()),
                    args.idempotency_key,
                )
            elif cmd == "wait":
                result = c.wait_commitment(
                    conn,
                    args.commitment_id,
                    args.task,
                    args.agent,
                    args.expected_version,
                    args.next_check_at,
                    args.deadline,
                    args.signal_expected,
                    args.idempotency_key,
                )
            elif cmd == "signal":
                result = c.signal_commitment(
                    conn,
                    args.commitment_id,
                    args.source,
                    args.external_id,
                    args.external_ref,
                    args.note,
                    args.actor,
                )
            elif cmd == "adopt":
                result = c.adopt_commitment(
                    conn,
                    args.commitment_id,
                    args.followup_task,
                    args.actor,
                    args.expected_version,
                    args.reason,
                    args.idempotency_key,
                )
            elif cmd == "cancel":
                result = c.cancel_commitment(
                    conn, args.commitment_id, args.actor, args.expected_version, args.reason
                )
        print_json(result)
    finally:
        conn.close()
    return True
