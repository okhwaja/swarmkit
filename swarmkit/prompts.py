"""Build fresh agent context and write role prompts."""

from pathlib import Path
import json
import shlex

from .core import PACKAGE_ROOT, CLI_PATH, SwarmError, json_dump, make_id
from .inbox import inbox
from .queries import case_dict, decision_dict, mission_snapshot, task_dict
from .storage import case_row, connect, decision_row, task_row


def guidance_path(role):
    return PACKAGE_ROOT / "guidance" / (role + ".md")


def role_for_task(task):
    if task["kind"] == "briefing":
        return "briefer"
    if task["kind"] == "verification":
        return "verifier"
    return "worker"


def build_prompt(root, role, agent, task_id=None):
    conn = connect(root)
    try:
        conn.execute("BEGIN")
        snapshot = mission_snapshot(conn)
        watermark = conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
        active_case_details = (
            [
                case_dict(conn, row)
                for row in conn.execute(
                    "SELECT * FROM cases WHERE status NOT IN ('DONE','CANCELLED') ORDER BY priority DESC, created_at"
                )
            ]
            if role == "manager"
            else []
        )
        unseen = inbox(conn, agent, advance=False, task_id=task_id)
        task = None
        if task_id:
            task = task_dict(conn, task_row(conn, task_id))
            linked = [decision_dict(conn, decision_row(conn, d)) for d in task["decisions"]]
            linked_cases = [
                case_dict(conn, case_row(conn, case_id)) for case_id in task["case_ids"]
            ]
        else:
            linked = []
            linked_cases = []
    finally:
        conn.close()
    cli = CLI_PATH
    command_prefix = "python3 %s --root %s" % (shlex.quote(str(cli)), shlex.quote(str(root)))
    guide = guidance_path(role)
    if not guide.exists():
        raise SwarmError("Missing role guidance: %s" % guide)
    guide_text = guide.read_text(encoding="utf-8")
    guide_text = guide_text.replace("<command_prefix>", command_prefix)
    guide_text = guide_text.replace("<agent_id>", agent)
    if task_id:
        guide_text = guide_text.replace("<task_id>", task_id)
    context = {
        "event_watermark": watermark,
        "agent_id": agent,
        "role": role,
        "command_prefix": command_prefix,
        "mission": snapshot["mission"],
        "task": task,
        "linked_cases": linked_cases,
        "linked_decisions": linked,
        "unseen_events": unseen,
    }
    if role == "manager":
        context["pending_manager_reviews"] = [
            item for item in snapshot["manager_reviews"] if item["status"] in {"PENDING", "RUNNING"}
        ]
        context["open_findings"] = [
            item for item in snapshot["findings"] if item["status"] == "OPEN"
        ]
        context["active_external_waits"] = [
            item for item in snapshot["external_waits"] if item["status"] == "WAITING"
        ]
        context["recent_wakeups"] = sorted(
            [item for item in snapshot["external_waits"] if item["status"] == "WOKEN"],
            key=lambda item: item["woke_at"] or "",
            reverse=True,
        )[:10]
        context["installed_policies"] = snapshot["policies"]
        context["active_policy_applications"] = [
            item
            for item in snapshot["policy_applications"]
            if item["status"] not in {"DONE", "CANCELLED"}
        ]
        context["recent_terminal_policy_applications"] = [
            {
                "id": item["id"],
                "policy_id": item["policy_id"],
                "policy_version": item["policy_version"],
                "status": item["status"],
                "created_at": item["created_at"],
            }
            for item in snapshot["policy_applications"]
            if item["status"] in {"DONE", "CANCELLED"}
        ][-10:]
        context["active_cases"] = [item for item in active_case_details]
        context["recent_terminal_cases"] = sorted(
            [item for item in snapshot["cases"] if item["status"] in {"DONE", "CANCELLED"}],
            key=lambda item: item["updated_at"],
            reverse=True,
        )[:10]
        context["installed_extensions"] = snapshot["extensions"]
        context["delivery_outbox"] = [
            {
                "id": item["id"],
                "status": item["status"],
                "channel": item["channel"],
                "extension_id": item["extension_id"],
                "subject": item["subject"],
                "attempt_count": item["attempt_count"],
                "last_error": item["last_error"],
            }
            for item in (
                [
                    delivery
                    for delivery in snapshot["deliveries"]
                    if delivery["status"] not in {"SENT", "CANCELLED"}
                ]
                + [
                    delivery
                    for delivery in snapshot["deliveries"]
                    if delivery["status"] in {"SENT", "CANCELLED"}
                ][-10:]
            )
        ]

    def bounded(value, depth=0):
        if isinstance(value, str) and len(value) > 4000:
            return value[:4000] + "\n[truncated; fetch full entity with CLI]"
        if isinstance(value, list):
            result = [bounded(item, depth + 1) for item in value[:20]]
            if len(value) > 20:
                result.append(
                    {"omitted_items": len(value) - 20, "retrieve": "Use the CLI list/show commands"}
                )
            return result
        if isinstance(value, dict):
            return {key: bounded(item, depth + 1) for key, item in value.items()}
        return value

    context = bounded(context)
    if len(json_dump(context).encode("utf-8")) > 64000:
        context = {
            "event_watermark": watermark,
            "agent_id": agent,
            "role": role,
            "task_id": task_id,
            "command_prefix": command_prefix,
            "retrieve": "Context exceeded 64KB. Fetch status, task show, and inbox --lease before acting.",
        }
    return "\n".join(
        [
            guide_text.rstrip(),
            "",
            "# Invocation context",
            "",
            "The JSON below is generated from canonical state. Re-read state with the CLI before acting if anything may have changed.",
            "",
            "```json",
            json.dumps(context, indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )


def write_prompt(root, role, agent, task_id=None):
    prompt = build_prompt(root, role, agent, task_id)
    name = "%s-%s.md" % (make_id("P"), role)
    path = root / "prompts" / name
    with path.open("x", encoding="utf-8") as handle:
        handle.write(prompt)
    return path
