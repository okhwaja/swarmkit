"""Argument parsing and command routing. Domain rules live in the owning modules."""

import argparse
import sqlite3
import sys

from .audit import export_audit, verify_audit
from .cases import add_case_signal, apply_policy_to_case, cancel_case, link_case_task, open_case
from .coordination import (
    commit_review,
    dispose_finding,
    raise_finding,
    reconcile_conn,
    reconcile_deliveries,
    signal_external_wait,
    start_external_wait,
)
from .core import (
    SwarmError,
    VALID_BLOCKER_KINDS,
    VALID_CASE_STATES,
    VALID_DELIVERY_STATES,
    VALID_FINDING_SIGNIFICANCE,
    VALID_FINDING_STATES,
    VALID_FORECAST_CONFIDENCE,
    VALID_MISSION_MODES,
    VALID_TASK_KINDS,
    VALID_WAIT_STATES,
    VALID_WORKSTREAM_STATES,
    VERSION,
    json_load,
    print_json,
    root_path,
    utcnow,
)
from .decisions import (
    acknowledge_decision,
    link_decision,
    require_decision_choice,
    resolve_decision,
    revise_decision,
)
from .delivery import (
    cancel_delivery,
    claim_delivery,
    dispatch_delivery,
    enqueue_delivery,
    install_extension,
    mark_delivery_failed,
    mark_delivery_sent,
    read_extension_source,
    retry_delivery,
)
from .diagnostics import doctor
from .effects import acquire_resource, prepare_effect, release_resource, transition_effect
from .evidence import evidence_gaps, record_evidence, set_contract
from .inbox import ack_inbox, inbox, lease_inbox
from .policies import apply_policy, install_policy, read_policy_source
from .prompts import build_prompt, write_prompt
from .queries import (
    case_dict,
    decision_dict,
    delivery_dict,
    explain_state,
    extension_dict,
    extension_summary,
    external_wait_dict,
    finding_dict,
    mission_snapshot,
    policy_application_dict,
    policy_pack_dict,
    policy_pack_summary,
    task_dict,
    workspace_dict,
    workstream_dict,
)
from .runtime import abandon_run, dispatch, recover_runs, run_loop, serve
from .setup import initialize, setup_check
from .storage import (
    add_event,
    case_row,
    connect,
    external_wait_row,
    finding_row,
    task_row,
    workstream_row,
)
from .tasks import (
    add_task,
    add_workstream,
    amend_mission,
    approve_task,
    block_task,
    cancel_task,
    checkpoint_task,
    claim_task,
    complete_mission,
    complete_task,
    configure_runtime,
    control_mission,
    link_task_workstream,
    record_fact,
    set_mission_phase,
    update_workstream,
)
from .views import render_board, render_status_report
from .workspaces import create_workspace, register_workspace


def add_runtime_cli(sub):
    for name in ("pause", "drain", "resume", "cancel", "abandon"):
        item = sub.add_parser(name, help="Set durable mission lifecycle state")
        item.add_argument("--reason", required=True)
        item.add_argument("--actor", default="human")
    recover = sub.add_parser(
        "recover", help="Recover stopped harnesses without rerunning uncertain effects"
    )
    recover.add_argument("--abandon-run")
    recover.add_argument("--reason")
    recover.add_argument("--actor", default="human")
    sub.add_parser("why", help="Explain blocked work, attempts, limits, and uncertain effects")
    configure = sub.add_parser(
        "configure", help="Set persistent runtime limits and evidence enforcement"
    )
    configure.add_argument("--limits", default="{}", help="JSON limits object")
    configure.add_argument("--strict-evidence", choices=["on", "off"])
    amend = sub.add_parser("amend", help="Version a paused mission and require explicit replanning")
    amend.add_argument("--objective", required=True)
    amend.add_argument("--success", action="append", default=[])
    amend.add_argument("--constraint", action="append", default=[])
    amend.add_argument("--reason", required=True)
    amend.add_argument("--actor", default="human")
    effect = sub.add_parser("effect", help="Track intent and receipts for external actions")
    es = effect.add_subparsers(dest="effect_command", required=True)
    ep = es.add_parser("prepare")
    for name in ("task", "agent", "key", "target", "revision"):
        ep.add_argument("--" + name, required=True)
    ep.add_argument("--parameters", default="{}", help="JSON action parameters")
    es.add_parser("list")
    for name in ("start", "succeeded", "failed", "unknown", "not-applied"):
        item = es.add_parser(name)
        item.add_argument("effect_id")
        item.add_argument("--actor", required=True)
        item.add_argument("--receipt", required=name != "start")
    resource = sub.add_parser("resource", help="Lease exclusive resources with attempt fencing")
    rs = resource.add_subparsers(dest="resource_command", required=True)
    ra = rs.add_parser("acquire")
    ra.add_argument("resource")
    ra.add_argument("--task", required=True)
    ra.add_argument("--agent", required=True)
    ra.add_argument("--lease-seconds", type=int, default=300)
    rr = rs.add_parser("release")
    rr.add_argument("token")
    rr.add_argument("--agent", required=True)
    rs.add_parser("list")
    evidence = sub.add_parser(
        "evidence", help="Bind result files to criteria, revision, and environment"
    )
    vs = evidence.add_subparsers(dest="evidence_command", required=True)
    vc = vs.add_parser("contract")
    for name in ("task", "revision", "environment"):
        vc.add_argument("--" + name, required=True)
    vc.add_argument("--actor", default="manager")
    vr = vs.add_parser("record")
    for name in ("task", "agent", "criterion", "revision", "environment", "command", "path"):
        vr.add_argument(
            "--" + name, required=True, dest="evidence_command_text" if name == "command" else name
        )
    vr.add_argument("--exit-code", type=int, required=True)
    vg = vs.add_parser("gaps")
    vg.add_argument("--task", required=True)
    review = sub.add_parser(
        "review-commit", help="Record a semantic disposition for every manager trigger"
    )
    review.add_argument("review_id")
    review.add_argument("--agent", required=True)
    review.add_argument("--dispositions", required=True, help="JSON list in trigger order")
    review.add_argument("--summary", required=True)
    workspace = sub.add_parser(
        "workspace", help="Create, register, or inspect task-specific isolated checkouts"
    )
    ws = workspace.add_subparsers(dest="workspace_command", required=True)
    wc = ws.add_parser("create")
    wc.add_argument("--task", required=True)
    wc.add_argument("--repository", required=True)
    wc.add_argument("--base", required=True, help="Provider-specific base revision expression")
    wc.add_argument(
        "--provider",
        choices=["git", "command", "manual"],
        help="Override runner.json workspace provider",
    )
    wr = ws.add_parser(
        "register", help="Register a checkout created by the harness or an external tool"
    )
    wr.add_argument("--task", required=True)
    wr.add_argument(
        "--repository", required=True, help="Source directory; no VCS metadata required"
    )
    wr.add_argument("--path", required=True, help="Existing isolated checkout directory")
    wr.add_argument(
        "--base-revision", required=True, help="Exact provider-specific revision identifier"
    )
    wr.add_argument(
        "--workspace-ref",
        default="",
        help="Optional jj workspace name, branch, or internal checkout reference",
    )
    wr.add_argument("--agent", help="Required when registering for an active task attempt")
    ws.add_parser("list")
    service = sub.add_parser(
        "serve", help="Poll durable service state with bounded restartable scheduler runs"
    )
    service.add_argument("--max-polls", type=int, default=120)
    service.add_argument("--poll-seconds", type=float, default=30)
    service.add_argument("--max-cycles", type=int, default=20)
    audit = sub.add_parser("audit-verify", help="Verify every manifest file in an audit ZIP")
    audit.add_argument("archive")


def handle_runtime_cli(root, args):
    commands = {
        "pause",
        "drain",
        "resume",
        "cancel",
        "abandon",
        "recover",
        "why",
        "configure",
        "amend",
        "effect",
        "resource",
        "evidence",
        "review-commit",
        "workspace",
        "audit-verify",
        "serve",
    }
    if args.command not in commands:
        return False
    conn = connect(root)
    try:
        if args.command in {"pause", "drain", "resume", "cancel", "abandon"}:
            result = control_mission(conn, args.command, args.actor, args.reason)
        elif args.command == "recover":
            if args.abandon_run:
                if not args.reason:
                    raise SwarmError(
                        "--abandon-run requires --reason confirming the process stopped"
                    )
                abandon_run(conn, args.abandon_run, args.actor, args.reason)
            result = recover_runs(root, args.actor)
        elif args.command == "serve":
            result = serve(root, args.max_polls, args.poll_seconds, args.max_cycles)
        elif args.command == "why":
            result = explain_state(conn)
        elif args.command == "configure":
            result = configure_runtime(
                conn,
                json_load(args.limits),
                None if args.strict_evidence is None else args.strict_evidence == "on",
            )
        elif args.command == "amend":
            result = amend_mission(
                conn, args.objective, args.success, args.constraint, args.reason, args.actor
            )
        elif args.command == "effect":
            if args.effect_command == "prepare":
                result = prepare_effect(
                    conn,
                    args.task,
                    args.agent,
                    args.key,
                    args.target,
                    args.revision,
                    json_load(args.parameters),
                )
            elif args.effect_command == "list":
                result = [
                    dict(r) for r in conn.execute("SELECT * FROM effects ORDER BY created_at,id")
                ]
            else:
                result = transition_effect(
                    conn, args.effect_id, args.effect_command, args.actor, args.receipt
                )
        elif args.command == "resource":
            if args.resource_command == "acquire":
                result = acquire_resource(
                    conn, args.resource, args.task, args.agent, args.lease_seconds
                )
            elif args.resource_command == "release":
                release_resource(conn, args.token, args.agent)
                result = {"released": True}
            else:
                result = [
                    dict(r) for r in conn.execute("SELECT * FROM resource_leases ORDER BY resource")
                ]
        elif args.command == "evidence":
            if args.evidence_command == "contract":
                set_contract(conn, args.task, args.revision, args.environment, args.actor)
                result = {
                    "task_id": args.task,
                    "revision": args.revision,
                    "environment": args.environment,
                }
            elif args.evidence_command == "record":
                result = {
                    "evidence_id": record_evidence(
                        conn,
                        args.task,
                        args.agent,
                        args.criterion,
                        args.revision,
                        args.environment,
                        args.evidence_command_text,
                        args.exit_code,
                        args.path,
                    )
                }
            else:
                result = {"gaps": evidence_gaps(conn, args.task)}
        elif args.command == "review-commit":
            commit_review(
                conn, args.review_id, args.agent, json_load(args.dispositions), args.summary
            )
            result = {"review_id": args.review_id, "committed": True}
        elif args.command == "workspace":
            if args.workspace_command == "create":
                result = create_workspace(
                    root, conn, args.task, args.repository, args.base, args.provider
                )
            elif args.workspace_command == "register":
                result = register_workspace(
                    conn,
                    args.task,
                    args.repository,
                    args.path,
                    args.base_revision,
                    args.workspace_ref,
                    agent=args.agent,
                )
            else:
                result = [
                    workspace_dict(r)
                    for r in conn.execute("SELECT * FROM workspaces ORDER BY task_id")
                ]
        else:
            result = verify_audit(args.archive)
        print_json(result)
        return True
    finally:
        conn.close()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", help="Swarm workspace (default: $SWARM_ROOT or .swarm)")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)

    add_runtime_cli(sub)

    init = sub.add_parser("init", help="Create a mission workspace")
    init.add_argument("--objective", required=True)
    init.add_argument("--success", action="append", default=[], help="Repeatable success condition")
    init.add_argument(
        "--constraint", action="append", default=[], help="Repeatable safety or scope boundary"
    )
    init.add_argument(
        "--mode",
        type=str.upper,
        choices=sorted(VALID_MISSION_MODES),
        default="FINITE",
        help="FINITE completes once; SERVICE remains available for durable cases",
    )

    sub.add_parser("status", help="Show the current canonical snapshot")
    sub.add_parser("board", help="Regenerate the Markdown board")
    sub.add_parser("report", help="Generate the executive workstream and action report")
    sub.add_parser("reconcile", help="Apply deterministic readiness and lease transitions")
    sub.add_parser("doctor", help="Check state invariants")
    sub.add_parser("setup-check", help="Validate harness integration without launching an agent")

    ask = sub.add_parser("ask", help="Start a read-only briefing inquiry")
    ask.add_argument("--question", required=True)
    ask.add_argument("--workstream")
    ask.add_argument("--case")
    ask.add_argument("--depends-on", action="append", default=[])
    ask.add_argument("--actor", default="human")

    policy = sub.add_parser("policy", help="Install and apply reusable workflow policy packs")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    policy_install = policy_sub.add_parser("install")
    policy_install.add_argument("source", help="Policy directory or policy.json path")
    policy_install.add_argument("--actor", default="human")
    policy_install.add_argument("--force", action="store_true")
    policy_validate = policy_sub.add_parser("validate")
    policy_validate.add_argument("source", help="Policy directory or policy.json path")
    policy_sub.add_parser("list")
    policy_show = policy_sub.add_parser("show")
    policy_show.add_argument("policy_id")
    policy_apply = policy_sub.add_parser("apply")
    policy_apply.add_argument("policy_id")
    policy_apply.add_argument(
        "--var", action="append", default=[], help="Template value as name=value"
    )
    policy_apply.add_argument("--workstream")
    policy_apply.add_argument("--actor", default="manager")
    policy_apply.add_argument("--ready", action="store_true", help="Authorize all generated stages")
    policy_sub.add_parser("applications")
    policy_application = policy_sub.add_parser("application")
    policy_application.add_argument("application_id")

    case = sub.add_parser("case", help="Manage idempotent work requests for persistent services")
    case_sub = case.add_subparsers(dest="case_command", required=True)
    case_open = case_sub.add_parser("open")
    case_open.add_argument("--source", required=True)
    case_open.add_argument("--external-id", required=True)
    case_open.add_argument("--title", required=True)
    case_open.add_argument("--objective", required=True)
    case_open.add_argument("--priority", type=int, default=50)
    case_open.add_argument("--acceptance", action="append", default=[])
    case_open.add_argument("--payload")
    case_open.add_argument("--metadata", action="append", default=[], help="Repeatable name=value")
    case_open.add_argument("--policy")
    case_open.add_argument("--var", action="append", default=[], help="Policy value as name=value")
    case_open.add_argument("--ready", action="store_true")
    case_open.add_argument("--actor", default="ingress")
    case_list = case_sub.add_parser("list")
    case_list.add_argument("--status", type=str.upper, choices=sorted(VALID_CASE_STATES))
    case_show = case_sub.add_parser("show")
    case_show.add_argument("case_id")
    case_apply = case_sub.add_parser("apply-policy")
    case_apply.add_argument("case_id")
    case_apply.add_argument("policy_id")
    case_apply.add_argument("--var", action="append", default=[])
    case_apply.add_argument("--ready", action="store_true")
    case_apply.add_argument("--actor", default="manager")
    case_link = case_sub.add_parser("link-task")
    case_link.add_argument("case_id")
    case_link.add_argument("--task", required=True)
    case_link.add_argument("--actor", default="manager")
    case_signal = case_sub.add_parser("signal")
    case_signal.add_argument("case_id")
    case_signal.add_argument("--source", required=True)
    case_signal.add_argument("--external-id", required=True)
    case_signal.add_argument("--kind", required=True)
    case_signal.add_argument("--author")
    case_signal.add_argument("--body", required=True)
    case_signal.add_argument("--payload")
    case_signal.add_argument(
        "--metadata", action="append", default=[], help="Repeatable name=value"
    )
    case_signal.add_argument(
        "--decision", help="Resolve this linked open decision with the signal body"
    )
    case_signal.add_argument("--wake", action="store_true", help="Create a ready follow-up task")
    case_signal.add_argument("--actor", default="ingress")
    case_cancel = case_sub.add_parser("cancel")
    case_cancel.add_argument("case_id")
    case_cancel.add_argument("--reason", required=True)
    case_cancel.add_argument("--actor", default="human")

    extension = sub.add_parser("extension", help="Install delivery adapters for external systems")
    extension_sub = extension.add_subparsers(dest="extension_command", required=True)
    extension_install = extension_sub.add_parser("install")
    extension_install.add_argument("source", help="Extension directory or extension.json path")
    extension_install.add_argument("--actor", default="human")
    extension_install.add_argument("--force", action="store_true")
    extension_validate = extension_sub.add_parser("validate")
    extension_validate.add_argument("source", help="Extension directory or extension.json path")
    extension_sub.add_parser("list")
    extension_show = extension_sub.add_parser("show")
    extension_show.add_argument("extension_id")

    delivery = sub.add_parser("delivery", help="Manage the durable external-delivery outbox")
    delivery_sub = delivery.add_subparsers(dest="delivery_command", required=True)
    for name, help_text in (
        ("enqueue", "Snapshot an existing file and enqueue it"),
        ("enqueue-report", "Generate the current status report and enqueue it"),
    ):
        enqueue = delivery_sub.add_parser(name, help=help_text)
        enqueue.add_argument("--extension", required=True)
        enqueue.add_argument("--channel", required=True)
        enqueue.add_argument("--subject", required=True)
        enqueue.add_argument("--recipient", action="append", default=[], required=True)
        enqueue.add_argument(
            "--metadata", action="append", default=[], help="Repeatable name=value"
        )
        enqueue.add_argument("--idempotency-key", required=True)
        enqueue.add_argument("--actor", default="human")
        if name == "enqueue":
            enqueue.add_argument("--content", required=True)
    delivery_list = delivery_sub.add_parser("list")
    delivery_list.add_argument("--status", type=str.upper, choices=sorted(VALID_DELIVERY_STATES))
    delivery_show = delivery_sub.add_parser("show")
    delivery_show.add_argument("delivery_id")
    delivery_claim = delivery_sub.add_parser("claim")
    delivery_claim.add_argument("delivery_id")
    delivery_claim.add_argument("--agent", required=True)
    delivery_claim.add_argument("--lease-seconds", type=int, default=600)
    delivery_sent = delivery_sub.add_parser("sent")
    delivery_sent.add_argument("delivery_id")
    delivery_sent.add_argument("--agent", required=True)
    delivery_sent.add_argument("--receipt", required=True)
    delivery_fail = delivery_sub.add_parser("fail")
    delivery_fail.add_argument("delivery_id")
    delivery_fail.add_argument("--agent", required=True)
    delivery_fail.add_argument("--error", required=True)
    delivery_retry = delivery_sub.add_parser("retry")
    delivery_retry.add_argument("delivery_id")
    delivery_retry.add_argument("--actor", default="human")
    delivery_cancel = delivery_sub.add_parser("cancel")
    delivery_cancel.add_argument("delivery_id")
    delivery_cancel.add_argument("--actor", default="human")
    delivery_cancel.add_argument("--reason", required=True)
    delivery_dispatch = delivery_sub.add_parser("dispatch")
    delivery_dispatch.add_argument("delivery_id")
    delivery_dispatch.add_argument("--agent", required=True)
    delivery_dispatch.add_argument("--dry-run", action="store_true")

    workstream = sub.add_parser("workstream", help="Manage executive-level workstreams")
    workstream_sub = workstream.add_subparsers(dest="workstream_command", required=True)
    workstream_add = workstream_sub.add_parser("add")
    workstream_add.add_argument("--name", required=True)
    workstream_add.add_argument("--outcome", required=True)
    workstream_add.add_argument(
        "--status", type=str.upper, choices=sorted(VALID_WORKSTREAM_STATES), default="PLANNED"
    )
    workstream_add.add_argument("--actor", default="manager")
    workstream_update = workstream_sub.add_parser("update")
    workstream_update.add_argument("workstream_id")
    workstream_update.add_argument(
        "--status", type=str.upper, choices=sorted(VALID_WORKSTREAM_STATES)
    )
    workstream_update.add_argument("--summary")
    workstream_update.add_argument("--forecast-earliest")
    workstream_update.add_argument("--forecast-latest")
    workstream_update.add_argument(
        "--forecast-confidence", type=str.lower, choices=sorted(VALID_FORECAST_CONFIDENCE)
    )
    workstream_update.add_argument("--forecast-basis")
    workstream_update.add_argument("--actor", default="manager")
    workstream_link = workstream_sub.add_parser("link-task")
    workstream_link.add_argument("workstream_id")
    workstream_link.add_argument("--task", required=True)
    workstream_link.add_argument("--actor", default="manager")
    workstream_sub.add_parser("list")
    workstream_show = workstream_sub.add_parser("show")
    workstream_show.add_argument("workstream_id")

    task = sub.add_parser("task", help="Manage tasks")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    add = task_sub.add_parser("add")
    add.add_argument("--idempotency-key")
    add.add_argument("--title", required=True)
    add.add_argument("--description", required=True)
    add.add_argument("--kind", choices=sorted(VALID_TASK_KINDS), required=True)
    add.add_argument("--acceptance", action="append", default=[], required=True)
    add.add_argument("--depends-on", action="append", default=[])
    add.add_argument("--workstream", help="Executive workstream that owns this task")
    add.add_argument("--priority", type=int, default=50)
    add.add_argument("--actor", default="manager")
    add.add_argument("--ready", action="store_true", help="Authorize immediately")
    approve = task_sub.add_parser("approve")
    approve.add_argument("task_id")
    approve.add_argument("--actor", default="manager")
    claim = task_sub.add_parser("claim")
    claim.add_argument("task_id")
    claim.add_argument("--agent", required=True)
    claim.add_argument("--lease-seconds", type=int, default=1800)
    checkpoint = task_sub.add_parser("checkpoint")
    checkpoint.add_argument("task_id")
    checkpoint.add_argument("--agent", required=True)
    checkpoint.add_argument("--summary", required=True)
    checkpoint.add_argument("--next-action", required=True)
    checkpoint.add_argument("--lease-seconds", type=int, default=1800)
    complete = task_sub.add_parser("complete")
    complete.add_argument("task_id")
    complete.add_argument("--agent", required=True)
    complete.add_argument("--result", required=True)
    complete.add_argument("--verification", action="append", default=[], required=True)
    complete.add_argument("--artifact", action="append", default=[])
    cancel = task_sub.add_parser("cancel")
    cancel.add_argument("task_id")
    cancel.add_argument("--actor", default="manager")
    cancel.add_argument("--reason", required=True)
    block = task_sub.add_parser("block")
    block.add_argument("task_id")
    block.add_argument("--agent", required=True)
    block.add_argument("--kind", choices=sorted(VALID_BLOCKER_KINDS), required=True)
    block.add_argument("--question", required=True)
    block.add_argument("--recommendation")
    block.add_argument("--option", action="append", default=[])
    wait_external = task_sub.add_parser("wait-external")
    wait_external.add_argument("task_id")
    wait_external.add_argument("--agent", required=True)
    wait_external.add_argument("--condition", required=True)
    wait_external.add_argument("--external-ref", required=True)
    wait_external.add_argument("--next-check-at")
    wait_external.add_argument("--deadline", required=True)
    wait_external.add_argument("--signal-expected", action="store_true")
    task_sub.add_parser("list")
    show = task_sub.add_parser("show")
    show.add_argument("task_id")

    decision = sub.add_parser("decision", help="Manage durable decisions")
    decision_sub = decision.add_subparsers(dest="decision_command", required=True)
    decision_sub.add_parser("list")
    resolve = decision_sub.add_parser("resolve")
    resolve.add_argument("decision_id")
    resolve.add_argument("--answer", required=True)
    resolve.add_argument("--choice", help="Exact machine-readable option from the decision")
    resolve.add_argument("--actor", default="human")
    revise = decision_sub.add_parser("revise")
    revise.add_argument("decision_id")
    revise.add_argument("--answer", required=True)
    revise.add_argument("--choice", help="Exact machine-readable option from the decision")
    revise.add_argument("--actor", default="human")
    require_choice = decision_sub.add_parser("require-choice")
    require_choice.add_argument("decision_id")
    require_choice.add_argument("--choice", required=True)
    link = decision_sub.add_parser("link")
    link.add_argument("decision_id")
    link.add_argument("--task", required=True)
    link.add_argument("--actor", default="manager")
    ack = decision_sub.add_parser("ack")
    ack.add_argument("decision_id")
    ack.add_argument("--task", required=True)
    ack.add_argument("--agent", required=True)

    finding = sub.add_parser("finding", help="Elevate and disposition mission-relevant findings")
    finding_sub = finding.add_subparsers(dest="finding_command", required=True)
    finding_raise = finding_sub.add_parser("raise")
    finding_raise.add_argument("--task", required=True)
    finding_raise.add_argument("--agent", required=True)
    finding_raise.add_argument(
        "--significance", type=str.upper, choices=sorted(VALID_FINDING_SIGNIFICANCE), required=True
    )
    finding_raise.add_argument("--summary", required=True)
    finding_raise.add_argument("--evidence", action="append", default=[], required=True)
    finding_raise.add_argument("--impact", required=True)
    finding_raise.add_argument("--recommendation")
    finding_list = finding_sub.add_parser("list")
    finding_list.add_argument("--status", type=str.upper, choices=sorted(VALID_FINDING_STATES))
    finding_list.add_argument(
        "--significance", type=str.upper, choices=sorted(VALID_FINDING_SIGNIFICANCE)
    )
    finding_show = finding_sub.add_parser("show")
    finding_show.add_argument("finding_id")
    finding_dispose = finding_sub.add_parser("disposition")
    finding_dispose.add_argument("finding_id")
    finding_dispose.add_argument(
        "--status", type=str.upper, choices=sorted(VALID_FINDING_STATES - {"OPEN"}), required=True
    )
    finding_dispose.add_argument("--rationale", required=True)
    finding_dispose.add_argument("--task", action="append", default=[])
    finding_dispose.add_argument("--workstream", action="append", default=[])
    finding_dispose.add_argument("--actor", default="manager")

    wait = sub.add_parser("wait", help="Inspect and signal durable external waits")
    wait_sub = wait.add_subparsers(dest="wait_command", required=True)
    wait_list = wait_sub.add_parser("list")
    wait_list.add_argument("--status", type=str.upper, choices=sorted(VALID_WAIT_STATES))
    wait_show = wait_sub.add_parser("show")
    wait_show.add_argument("wait_id")
    wait_signal = wait_sub.add_parser("signal")
    wait_signal.add_argument("wait_id")
    wait_signal.add_argument("--source", required=True)
    wait_signal.add_argument("--external-id", required=True)
    wait_signal.add_argument("--note")
    wait_signal.add_argument("--actor", default="ingress")

    fact = sub.add_parser("fact", help="Record sourced, time-bounded operational facts")
    fact_sub = fact.add_subparsers(dest="fact_command", required=True)
    fact_list = fact_sub.add_parser("list")
    fact_list.add_argument("--include-expired", action="store_true")
    fact_record = fact_sub.add_parser("record")
    fact_record.add_argument("--subject", required=True)
    fact_record.add_argument("--value", required=True)
    fact_record.add_argument("--source", required=True)
    fact_record.add_argument("--actor", required=True)
    fact_record.add_argument("--task")
    fact_record.add_argument("--observed-at")
    fact_record.add_argument("--expires-at")
    fact_record.add_argument("--ttl-seconds", type=int)

    inbox_p = sub.add_parser("inbox", help="Read all events since an agent cursor")
    inbox_p.add_argument("--agent", required=True)
    inbox_p.add_argument("--task", help="Limit events to one task and its dependencies")
    inbox_p.add_argument("--after", type=int)
    inbox_p.add_argument(
        "--advance",
        action="store_true",
        help="Legacy read-and-advance; use --lease and --ack for reliable delivery",
    )
    inbox_p.add_argument("--lease", action="store_true")
    inbox_p.add_argument("--ack", help="Acknowledge a leased delivery token")
    inbox_p.add_argument("--limit", type=int, default=50)
    inbox_p.add_argument("--lease-seconds", type=int, default=300)

    prompt_p = sub.add_parser("prompt", help="Generate a grounded role prompt")
    prompt_p.add_argument(
        "--role",
        choices=["manager", "worker", "liaison", "status", "briefer", "verifier"],
        required=True,
    )
    prompt_p.add_argument("--agent", required=True)
    prompt_p.add_argument("--task")
    prompt_p.add_argument("--write", action="store_true")

    dispatch_p = sub.add_parser("dispatch", help="Invoke the configured third-party harness")
    dispatch_p.add_argument(
        "--role",
        choices=["manager", "worker", "liaison", "status", "briefer", "verifier"],
        required=True,
    )
    dispatch_p.add_argument("--agent", required=True)
    dispatch_p.add_argument("--task")
    dispatch_p.add_argument("--dry-run", action="store_true")

    run_p = sub.add_parser("run", help="Run manager/worker cycles through the configured harness")
    run_p.add_argument("--max-cycles", type=int, default=20)
    run_p.add_argument("--dry-run", action="store_true")

    mission_p = sub.add_parser("mission", help="Manage mission lifecycle")
    mission_sub = mission_p.add_subparsers(dest="mission_command", required=True)
    phase = mission_sub.add_parser("phase")
    phase.add_argument("phase")
    phase.add_argument("--actor", default="manager")
    done = mission_sub.add_parser("complete")
    done.add_argument("--evidence", required=True)
    done.add_argument("--actor", default="manager")
    done.add_argument("--shutdown-service", action="store_true")

    export_p = sub.add_parser("export", help="Create a reviewable audit ZIP")
    export_p.add_argument("--output", required=True)
    export_p.add_argument(
        "--share-safe",
        action="store_true",
        help="Export only allowlisted structural telemetry, excluding free text and files",
    )
    export_p.add_argument("--include-artifacts", action="store_true")
    export_p.add_argument("--max-artifact-mb", type=int, default=25)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    root = root_path(args.root)
    try:
        if args.command == "audit-verify":
            result = verify_audit(args.archive)
            print_json(result)
            return 0 if result["ok"] else 2
        if handle_runtime_cli(root, args):
            return 0
        if args.command == "init":
            mission_id = initialize(root, args.objective, args.success, args.constraint, args.mode)
            print_json(
                {
                    "root": str(root),
                    "mission_id": mission_id,
                    "mode": args.mode,
                    "board": str(root / "views" / "BOARD.md"),
                }
            )
            return 0

        if args.command == "board":
            print(render_board(root))
            return 0

        if args.command == "report":
            print(render_status_report(root))
            return 0

        if args.command == "reconcile":
            conn = connect(root)
            try:
                print_json({"changed": reconcile_conn(conn)})
            finally:
                conn.close()
            render_board(root)
            return 0

        if args.command == "status":
            conn = connect(root)
            try:
                reconcile_conn(conn)
                print_json(mission_snapshot(conn))
            finally:
                conn.close()
            return 0

        if args.command == "doctor":
            conn = connect(root)
            try:
                result = doctor(conn)
            finally:
                conn.close()
            print_json(result)
            return 0 if result["ok"] else 2

        if args.command == "setup-check":
            result = setup_check(root)
            print_json(result)
            return 0 if result["ok"] else 2

        if args.command == "ask":
            conn = connect(root)
            try:
                inquiry_case = case_row(conn, args.case) if args.case else None
                if (
                    inquiry_case
                    and args.workstream
                    and inquiry_case["workstream_id"] != args.workstream
                ):
                    raise SwarmError("Inquiry case and workstream do not match")
                workstream_id = inquiry_case["workstream_id"] if inquiry_case else args.workstream
                question = args.question.strip()
                if not question:
                    raise SwarmError("Inquiry question may not be empty")
                if inquiry_case and inquiry_case["status"] == "CANCELLED":
                    raise SwarmError("Cancelled case inquiries must use a separate workstream")
                if inquiry_case and inquiry_case["status"] == "DONE":
                    now = utcnow()
                    conn.execute(
                        "UPDATE cases SET status='ACTIVE', closed_at=NULL, updated_at=? WHERE id=?",
                        (now, inquiry_case["id"]),
                    )
                    conn.execute(
                        "UPDATE workstreams SET status='ACTIVE', updated_at=? WHERE id=?",
                        (now, inquiry_case["workstream_id"]),
                    )
                    add_event(
                        conn,
                        inquiry_case["mission_id"],
                        "case",
                        inquiry_case["id"],
                        "CASE_REOPENED_FOR_INQUIRY",
                        args.actor,
                        {"question": question},
                    )
                    conn.commit()
                title = "Inquiry: %s" % question.splitlines()[0][:100]
                task_id = add_task(
                    conn,
                    title,
                    question,
                    "briefing",
                    [
                        "Answer distinguishes observed facts from inference",
                        "Answer cites durable task, event, artifact, or source identifiers",
                        "Answer states confidence, uncertainty, and recommended next action",
                    ],
                    args.depends_on,
                    40,
                    args.actor,
                    True,
                    workstream_id,
                )
                if inquiry_case:
                    link_case_task(conn, inquiry_case["id"], task_id, args.actor)
                print_json(
                    {"inquiry_task_id": task_id, "next": "Run the orchestrator, then use task show"}
                )
            finally:
                conn.close()
            render_board(root)
            return 0

        if args.command == "case":
            conn = connect(root)
            try:
                if args.case_command == "open":
                    print_json(
                        open_case(
                            root,
                            conn,
                            args.source,
                            args.external_id,
                            args.title,
                            args.objective,
                            args.priority,
                            args.actor,
                            args.acceptance,
                            args.payload,
                            args.metadata,
                            args.policy,
                            args.var,
                            args.ready,
                        )
                    )
                elif args.case_command == "list":
                    reconcile_conn(conn)
                    if args.status:
                        rows = conn.execute(
                            "SELECT * FROM cases WHERE status=? ORDER BY priority DESC, created_at",
                            (args.status,),
                        )
                    else:
                        rows = conn.execute(
                            "SELECT * FROM cases ORDER BY priority DESC, created_at"
                        )
                    print_json([case_dict(conn, row) for row in rows])
                elif args.case_command == "show":
                    reconcile_conn(conn)
                    print_json(case_dict(conn, case_row(conn, args.case_id)))
                elif args.case_command == "apply-policy":
                    print_json(
                        apply_policy_to_case(
                            conn,
                            args.case_id,
                            args.policy_id,
                            args.var,
                            args.actor,
                            args.ready,
                        )
                    )
                elif args.case_command == "link-task":
                    print_json(
                        {
                            "case_id": args.case_id,
                            "task_id": args.task,
                            "changed": link_case_task(conn, args.case_id, args.task, args.actor),
                        }
                    )
                elif args.case_command == "signal":
                    print_json(
                        add_case_signal(
                            root,
                            conn,
                            args.case_id,
                            args.source,
                            args.external_id,
                            args.kind,
                            args.author,
                            args.body,
                            args.actor,
                            args.payload,
                            args.metadata,
                            args.decision,
                            args.wake,
                        )
                    )
                elif args.case_command == "cancel":
                    cancel_case(conn, args.case_id, args.actor, args.reason)
                    print_json({"case_id": args.case_id, "status": "CANCELLED"})
            finally:
                conn.close()
            render_board(root)
            render_status_report(root)
            return 0

        if args.command == "policy":
            if args.policy_command == "validate":
                manifest, guidance, manifest_path = read_policy_source(args.source)
                print_json(
                    {
                        "ok": True,
                        "manifest_path": str(manifest_path),
                        "id": manifest["id"],
                        "version": manifest["version"],
                        "stage_count": len(manifest["stages"]),
                        "guidance_bytes": len(guidance.encode("utf-8")),
                    }
                )
                return 0
            conn = connect(root)
            try:
                if args.policy_command == "install":
                    print_json(install_policy(conn, args.source, args.actor, args.force))
                elif args.policy_command == "list":
                    print_json(
                        [
                            policy_pack_summary(conn, row)
                            for row in conn.execute("SELECT * FROM policy_packs ORDER BY id")
                        ]
                    )
                elif args.policy_command == "show":
                    row = conn.execute(
                        "SELECT * FROM policy_packs WHERE id=?", (args.policy_id,)
                    ).fetchone()
                    if not row:
                        raise SwarmError("Unknown installed policy: %s" % args.policy_id)
                    print_json(policy_pack_dict(conn, row))
                elif args.policy_command == "apply":
                    print_json(
                        apply_policy(
                            conn,
                            args.policy_id,
                            args.var,
                            args.workstream,
                            args.actor,
                            args.ready,
                        )
                    )
                elif args.policy_command == "applications":
                    print_json(
                        [
                            policy_application_dict(conn, row["id"])
                            for row in conn.execute(
                                "SELECT id FROM policy_applications ORDER BY created_at"
                            )
                        ]
                    )
                elif args.policy_command == "application":
                    print_json(
                        policy_application_dict(conn, args.application_id, include_definition=True)
                    )
            finally:
                conn.close()
            if args.policy_command in {"install", "apply"}:
                render_board(root)
            return 0

        if args.command == "extension":
            if args.extension_command == "validate":
                manifest, guidance, manifest_path = read_extension_source(args.source)
                print_json(
                    {
                        "ok": True,
                        "manifest_path": str(manifest_path),
                        "id": manifest["id"],
                        "version": manifest["version"],
                        "kind": manifest["kind"],
                        "handles": manifest["handles"],
                        "executor_type": manifest["executor"]["type"],
                        "guidance_bytes": len(guidance.encode("utf-8")),
                    }
                )
                return 0
            conn = connect(root)
            try:
                if args.extension_command == "install":
                    print_json(install_extension(conn, args.source, args.actor, args.force))
                elif args.extension_command == "list":
                    print_json(
                        [
                            extension_summary(row)
                            for row in conn.execute("SELECT * FROM extensions ORDER BY id")
                        ]
                    )
                elif args.extension_command == "show":
                    row = conn.execute(
                        "SELECT * FROM extensions WHERE id=?", (args.extension_id,)
                    ).fetchone()
                    if not row:
                        raise SwarmError("Unknown installed extension: %s" % args.extension_id)
                    print_json(extension_dict(row))
            finally:
                conn.close()
            if args.extension_command == "install":
                render_board(root)
            return 0

        if args.command == "delivery":
            if args.delivery_command == "dispatch":
                print_json(dispatch_delivery(root, args.delivery_id, args.agent, args.dry_run))
                if not args.dry_run:
                    render_board(root)
                return 0
            content = None
            if args.delivery_command == "enqueue-report":
                content = render_status_report(root)
            conn = connect(root)
            try:
                if args.delivery_command in {"enqueue", "enqueue-report"}:
                    print_json(
                        enqueue_delivery(
                            root,
                            conn,
                            args.extension,
                            args.channel,
                            args.subject,
                            args.recipient,
                            content or args.content,
                            args.metadata,
                            args.idempotency_key,
                            args.actor,
                        )
                    )
                elif args.delivery_command == "list":
                    reconcile_deliveries(conn)
                    if args.status:
                        rows = conn.execute(
                            "SELECT * FROM deliveries WHERE status=? ORDER BY created_at",
                            (args.status,),
                        )
                    else:
                        rows = conn.execute("SELECT * FROM deliveries ORDER BY created_at")
                    print_json([delivery_dict(conn, row) for row in rows])
                elif args.delivery_command == "show":
                    reconcile_deliveries(conn)
                    row = conn.execute(
                        "SELECT * FROM deliveries WHERE id=?", (args.delivery_id,)
                    ).fetchone()
                    if not row:
                        raise SwarmError("Unknown delivery: %s" % args.delivery_id)
                    print_json(delivery_dict(conn, row))
                elif args.delivery_command == "claim":
                    print_json(
                        claim_delivery(conn, args.delivery_id, args.agent, args.lease_seconds)
                    )
                elif args.delivery_command == "sent":
                    mark_delivery_sent(conn, args.delivery_id, args.agent, args.receipt)
                    print_json({"delivery_id": args.delivery_id, "status": "SENT"})
                elif args.delivery_command == "fail":
                    mark_delivery_failed(conn, args.delivery_id, args.agent, args.error)
                    print_json({"delivery_id": args.delivery_id, "status": "FAILED"})
                elif args.delivery_command == "retry":
                    retry_delivery(conn, args.delivery_id, args.actor)
                    print_json({"delivery_id": args.delivery_id, "status": "PENDING"})
                elif args.delivery_command == "cancel":
                    cancel_delivery(conn, args.delivery_id, args.actor, args.reason)
                    print_json({"delivery_id": args.delivery_id, "status": "CANCELLED"})
            finally:
                conn.close()
            render_board(root)
            return 0

        if args.command == "workstream":
            conn = connect(root)
            try:
                if args.workstream_command == "add":
                    workstream_id = add_workstream(
                        conn, args.name, args.outcome, args.actor, args.status
                    )
                    print_json({"workstream_id": workstream_id})
                elif args.workstream_command == "update":
                    update_workstream(
                        conn,
                        args.workstream_id,
                        args.actor,
                        args.status,
                        args.summary,
                        args.forecast_earliest,
                        args.forecast_latest,
                        args.forecast_confidence,
                        args.forecast_basis,
                    )
                    print_json(workstream_dict(conn, workstream_row(conn, args.workstream_id)))
                elif args.workstream_command == "link-task":
                    changed = link_task_workstream(conn, args.workstream_id, args.task, args.actor)
                    print_json(
                        {
                            "workstream_id": args.workstream_id,
                            "task_id": args.task,
                            "changed": changed,
                        }
                    )
                elif args.workstream_command == "list":
                    print_json(
                        [
                            workstream_dict(conn, row)
                            for row in conn.execute("SELECT * FROM workstreams ORDER BY created_at")
                        ]
                    )
                elif args.workstream_command == "show":
                    print_json(workstream_dict(conn, workstream_row(conn, args.workstream_id)))
            finally:
                conn.close()
            render_board(root)
            render_status_report(root)
            return 0

        if args.command == "task":
            conn = connect(root)
            try:
                if args.task_command == "add":
                    task_id = add_task(
                        conn,
                        args.title,
                        args.description,
                        args.kind,
                        args.acceptance,
                        args.depends_on,
                        args.priority,
                        args.actor,
                        args.ready,
                        args.workstream,
                        args.idempotency_key,
                    )
                    print_json({"task_id": task_id})
                elif args.task_command == "approve":
                    approve_task(conn, args.task_id, args.actor)
                    print_json({"task_id": args.task_id, "authorized": True})
                elif args.task_command == "claim":
                    generation = claim_task(conn, args.task_id, args.agent, args.lease_seconds)
                    print_json(
                        {"task_id": args.task_id, "agent": args.agent, "generation": generation}
                    )
                elif args.task_command == "checkpoint":
                    checkpoint_task(
                        conn,
                        args.task_id,
                        args.agent,
                        args.summary,
                        args.next_action,
                        args.lease_seconds,
                    )
                    print_json({"task_id": args.task_id, "status": "RUNNING"})
                elif args.task_command == "complete":
                    complete_task(
                        conn,
                        args.task_id,
                        args.agent,
                        args.result,
                        args.verification,
                        args.artifact,
                    )
                    print_json({"task_id": args.task_id, "status": "DONE"})
                elif args.task_command == "cancel":
                    cancel_task(conn, args.task_id, args.actor, args.reason)
                    print_json({"task_id": args.task_id, "status": "CANCELLED"})
                elif args.task_command == "block":
                    decision_id = block_task(
                        conn,
                        args.task_id,
                        args.agent,
                        args.kind,
                        args.question,
                        args.recommendation,
                        args.option,
                    )
                    print_json(
                        {"task_id": args.task_id, "status": "BLOCKED", "decision_id": decision_id}
                    )
                elif args.task_command == "wait-external":
                    print_json(
                        start_external_wait(
                            conn,
                            args.task_id,
                            args.agent,
                            args.condition,
                            args.external_ref,
                            args.deadline,
                            args.next_check_at,
                            args.signal_expected,
                        )
                    )
                elif args.task_command == "list":
                    reconcile_conn(conn)
                    print_json(
                        [
                            task_dict(conn, r)
                            for r in conn.execute(
                                "SELECT * FROM tasks ORDER BY priority DESC, created_at"
                            )
                        ]
                    )
                elif args.task_command == "show":
                    reconcile_conn(conn)
                    print_json(task_dict(conn, task_row(conn, args.task_id)))
            finally:
                conn.close()
            render_board(root)
            return 0

        if args.command == "finding":
            conn = connect(root)
            try:
                if args.finding_command == "raise":
                    finding_id = raise_finding(
                        conn,
                        args.task,
                        args.agent,
                        args.significance,
                        args.summary,
                        args.evidence,
                        args.impact,
                        args.recommendation,
                    )
                    print_json(finding_dict(conn, finding_row(conn, finding_id)))
                elif args.finding_command == "list":
                    clauses = []
                    values = []
                    if args.status:
                        clauses.append("status=?")
                        values.append(args.status)
                    if args.significance:
                        clauses.append("significance=?")
                        values.append(args.significance)
                    where = " WHERE " + " AND ".join(clauses) if clauses else ""
                    rows = conn.execute(
                        "SELECT * FROM findings%s ORDER BY created_at" % where,
                        values,
                    )
                    print_json([finding_dict(conn, row) for row in rows])
                elif args.finding_command == "show":
                    print_json(finding_dict(conn, finding_row(conn, args.finding_id)))
                elif args.finding_command == "disposition":
                    print_json(
                        dispose_finding(
                            conn,
                            args.finding_id,
                            args.status,
                            args.rationale,
                            args.actor,
                            args.task,
                            args.workstream,
                        )
                    )
            finally:
                conn.close()
            render_board(root)
            render_status_report(root)
            return 0

        if args.command == "wait":
            conn = connect(root)
            try:
                reconcile_conn(conn)
                if args.wait_command == "list":
                    clauses = []
                    values = []
                    if args.status:
                        clauses.append("status=?")
                        values.append(args.status)
                    where = " WHERE " + " AND ".join(clauses) if clauses else ""
                    rows = conn.execute(
                        "SELECT * FROM external_waits%s ORDER BY created_at" % where,
                        values,
                    )
                    print_json([external_wait_dict(conn, row) for row in rows])
                elif args.wait_command == "show":
                    print_json(external_wait_dict(conn, external_wait_row(conn, args.wait_id)))
                elif args.wait_command == "signal":
                    print_json(
                        signal_external_wait(
                            conn,
                            args.wait_id,
                            args.source,
                            args.external_id,
                            args.actor,
                            args.note,
                        )
                    )
            finally:
                conn.close()
            render_board(root)
            render_status_report(root)
            return 0

        if args.command == "decision":
            conn = connect(root)
            try:
                if args.decision_command == "list":
                    reconcile_conn(conn)
                    print_json(
                        [
                            decision_dict(conn, r)
                            for r in conn.execute(
                                "SELECT * FROM decisions ORDER BY status, created_at"
                            )
                        ]
                    )
                elif args.decision_command == "resolve":
                    version = resolve_decision(
                        conn,
                        args.decision_id,
                        args.answer,
                        args.actor,
                        args.choice,
                    )
                    print_json(
                        {
                            "decision_id": args.decision_id,
                            "status": "RESOLVED",
                            "selected_option": args.choice,
                            "version": version,
                        }
                    )
                elif args.decision_command == "revise":
                    version = revise_decision(
                        conn,
                        args.decision_id,
                        args.answer,
                        args.actor,
                        args.choice,
                    )
                    print_json(
                        {
                            "decision_id": args.decision_id,
                            "status": "RESOLVED",
                            "selected_option": args.choice,
                            "version": version,
                        }
                    )
                elif args.decision_command == "require-choice":
                    print_json(require_decision_choice(conn, args.decision_id, args.choice))
                elif args.decision_command == "link":
                    linked = link_decision(conn, args.decision_id, args.task, args.actor)
                    print_json(
                        {"decision_id": args.decision_id, "task_id": args.task, "linked": linked}
                    )
                elif args.decision_command == "ack":
                    acknowledge_decision(conn, args.decision_id, args.task, args.agent)
                    print_json(
                        {
                            "decision_id": args.decision_id,
                            "task_id": args.task,
                            "acknowledged": True,
                        }
                    )
            finally:
                conn.close()
            render_board(root)
            return 0

        if args.command == "fact":
            conn = connect(root)
            try:
                if args.fact_command == "list":
                    reconcile_conn(conn)
                    if args.include_expired:
                        rows = conn.execute(
                            "SELECT * FROM facts ORDER BY subject, observed_at DESC"
                        )
                    else:
                        rows = conn.execute(
                            "SELECT * FROM facts WHERE status='CURRENT' ORDER BY subject"
                        )
                    print_json([dict(row) for row in rows])
                else:
                    fact_id = record_fact(
                        conn,
                        args.subject,
                        args.value,
                        args.source,
                        args.actor,
                        args.task,
                        args.observed_at,
                        args.expires_at,
                        args.ttl_seconds,
                    )
                    print_json({"fact_id": fact_id})
            finally:
                conn.close()
            render_board(root)
            return 0

        if args.command == "inbox":
            conn = connect(root)
            try:
                reconcile_conn(conn)
                if args.ack:
                    print_json(ack_inbox(conn, args.ack, args.agent))
                elif args.lease:
                    print_json(
                        lease_inbox(conn, args.agent, args.task, args.limit, args.lease_seconds)
                    )
                else:
                    print_json(inbox(conn, args.agent, args.after, args.advance, args.task))
            finally:
                conn.close()
            return 0

        if args.command == "prompt":
            if args.write:
                print(write_prompt(root, args.role, args.agent, args.task))
            else:
                print(build_prompt(root, args.role, args.agent, args.task))
            return 0

        if args.command == "dispatch":
            print_json(dispatch(root, args.role, args.agent, args.task, args.dry_run))
            render_board(root)
            return 0

        if args.command == "run":
            print_json(run_loop(root, args.max_cycles, args.dry_run))
            render_board(root)
            return 0

        if args.command == "mission":
            conn = connect(root)
            try:
                if args.mission_command == "phase":
                    set_mission_phase(conn, args.phase, args.actor)
                    print_json({"phase": args.phase.upper()})
                else:
                    complete_mission(conn, args.evidence, args.actor, args.shutdown_service)
                    print_json({"status": "DONE"})
            finally:
                conn.close()
            render_board(root)
            return 0

        if args.command == "export":
            print(
                export_audit(
                    root, args.output, args.include_artifacts, args.max_artifact_mb, args.share_safe
                )
            )
            return 0
    except (
        SwarmError,
        sqlite3.Error,
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ) as exc:
        print("swarmctl: %s" % exc, file=sys.stderr)
        return 2
    return 1
