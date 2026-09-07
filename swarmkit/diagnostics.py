"""Check database consistency and report actionable integrity problems."""

import datetime as dt

from .core import (
    ACTIVE_TASK_STATES,
    SwarmError,
    VALID_CASE_STATES,
    VALID_DELIVERY_STATES,
    VALID_FINDING_SIGNIFICANCE,
    VALID_FINDING_STATES,
    VALID_MANAGER_REVIEW_STATES,
    VALID_MISSION_MODES,
    VALID_TASK_STATES,
    VALID_WAIT_STATES,
    VALID_WAKE_REASONS,
    case_payload_intact,
    delivery_content_intact,
    json_load,
    parse_time,
)
from .delivery import validate_extension_manifest
from .policies import validate_policy_manifest
from .storage import mission, mission_mode, open_decision_count


def doctor(conn):
    problems = []
    now = dt.datetime.now(dt.timezone.utc)
    current_mission = mission(conn)
    if mission_mode(conn) not in VALID_MISSION_MODES:
        problems.append(
            {
                "severity": "error",
                "entity": current_mission["id"],
                "problem": "invalid mission mode",
            }
        )
    for row in conn.execute("SELECT * FROM tasks"):
        if row["status"] not in VALID_TASK_STATES:
            problems.append(
                {"severity": "error", "entity": row["id"], "problem": "invalid task state"}
            )
        if row["status"] in ACTIVE_TASK_STATES and not row["owner"]:
            problems.append(
                {"severity": "error", "entity": row["id"], "problem": "active task has no owner"}
            )
        if row["status"] in ACTIVE_TASK_STATES and not row["lease_until"]:
            problems.append(
                {"severity": "error", "entity": row["id"], "problem": "active task has no lease"}
            )
        if (
            row["lease_until"]
            and parse_time(row["lease_until"]) < now
            and row["status"] in ACTIVE_TASK_STATES
        ):
            problems.append(
                {"severity": "warning", "entity": row["id"], "problem": "task lease is expired"}
            )
        if row["status"] == "DONE" and not json_load(row["verification_json"], []):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "done task lacks verification",
                }
            )
        if row["status"] == "BLOCKED" and open_decision_count(conn, row["id"]) == 0:
            problems.append(
                {
                    "severity": "warning",
                    "entity": row["id"],
                    "problem": "blocked task has no open decision",
                }
            )
        active_waits = conn.execute(
            "SELECT COUNT(*) AS n FROM external_waits WHERE task_id=? AND status='WAITING'",
            (row["id"],),
        ).fetchone()["n"]
        if row["status"] == "WAITING_EXTERNAL" and active_waits != 1:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "externally waiting task must have exactly one active wait",
                }
            )
        if row["status"] != "WAITING_EXTERNAL" and active_waits:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "active external wait belongs to a task not in WAITING_EXTERNAL",
                }
            )
        if row["status"] == "WAITING_EXTERNAL" and (row["owner"] or row["lease_until"]):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "externally waiting task retains owner or lease",
                }
            )
        if current_mission["phase"] != "DISCOVERY":
            linked = conn.execute(
                "SELECT 1 FROM task_workstreams WHERE task_id=?", (row["id"],)
            ).fetchone()
            if not linked:
                problems.append(
                    {
                        "severity": "warning",
                        "entity": row["id"],
                        "problem": "task is not assigned to an executive workstream",
                    }
                )
    for row in conn.execute("SELECT * FROM workstreams"):
        if row["status"] in {"ACTIVE", "BLOCKED", "VERIFYING"} and not row["progress_summary"]:
            problems.append(
                {
                    "severity": "warning",
                    "entity": row["id"],
                    "problem": "active workstream lacks a progress summary",
                }
            )
        linked_counts = conn.execute(
            """SELECT COUNT(*) AS total,
               SUM(CASE WHEN t.status NOT IN ('DONE','CANCELLED') THEN 1 ELSE 0 END) AS remaining,
               SUM(CASE WHEN t.status IN ('CLAIMED','RUNNING','VERIFYING') THEN 1 ELSE 0 END) AS active
               FROM task_workstreams tw JOIN tasks t ON t.id=tw.task_id WHERE tw.workstream_id=?""",
            (row["id"],),
        ).fetchone()
        if row["status"] == "PLANNED" and (linked_counts["active"] or 0):
            problems.append(
                {
                    "severity": "warning",
                    "entity": row["id"],
                    "problem": "planned workstream has active tasks",
                }
            )
        if (
            row["status"] in {"ACTIVE", "BLOCKED", "VERIFYING"}
            and linked_counts["total"]
            and not linked_counts["remaining"]
        ):
            problems.append(
                {
                    "severity": "warning",
                    "entity": row["id"],
                    "problem": "all linked tasks are terminal but workstream is not closed",
                }
            )
        if (
            row["status"] not in {"DONE", "CANCELLED"}
            and row["forecast_latest"]
            and parse_time(row["forecast_latest"]) < now
        ):
            problems.append(
                {
                    "severity": "warning",
                    "entity": row["id"],
                    "problem": "latest forecast has passed; update the forecast and rationale",
                }
            )
        if row["status"] == "DONE":
            remaining = conn.execute(
                """SELECT COUNT(*) AS n FROM task_workstreams tw JOIN tasks t ON t.id=tw.task_id
                   WHERE tw.workstream_id=? AND t.status NOT IN ('DONE','CANCELLED')""",
                (row["id"],),
            ).fetchone()["n"]
            if remaining:
                problems.append(
                    {
                        "severity": "error",
                        "entity": row["id"],
                        "problem": "done workstream has non-terminal tasks",
                    }
                )
    for row in conn.execute("SELECT * FROM policy_packs"):
        try:
            validate_policy_manifest(json_load(row["manifest_json"], {}))
        except SwarmError as exc:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "invalid installed policy: %s" % exc,
                }
            )
    for row in conn.execute("SELECT * FROM policy_applications"):
        manifest = json_load(row["manifest_json"], {})
        expected = {stage["id"] for stage in manifest.get("stages", [])}
        actual = {
            item["stage_id"]
            for item in conn.execute(
                "SELECT stage_id FROM policy_application_tasks WHERE application_id=?", (row["id"],)
            )
        }
        if expected != actual:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "policy application stages do not match its manifest snapshot",
                }
            )
    for row in conn.execute("SELECT * FROM cases"):
        if row["status"] not in VALID_CASE_STATES:
            problems.append(
                {"severity": "error", "entity": row["id"], "problem": "invalid case state"}
            )
        if not case_payload_intact(
            row["payload_path"], row["payload_sha256"], row["payload_size_bytes"]
        ):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "initial case payload is missing or does not match its immutable hash",
                }
            )
        mismatched = conn.execute(
            """SELECT t.id FROM case_tasks ct JOIN tasks t ON t.id=ct.task_id
               LEFT JOIN task_workstreams tw ON tw.task_id=t.id
               WHERE ct.case_id=? AND (tw.workstream_id IS NULL OR tw.workstream_id <> ?)""",
            (row["id"], row["workstream_id"]),
        ).fetchall()
        if mismatched:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "case tasks are missing or assigned to another workstream",
                }
            )
    for row in conn.execute("SELECT * FROM case_signals"):
        if not case_payload_intact(
            row["payload_path"], row["payload_sha256"], row["payload_size_bytes"]
        ):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "case signal payload is missing or does not match its immutable hash",
                }
            )
    for row in conn.execute("SELECT * FROM external_waits"):
        if row["status"] not in VALID_WAIT_STATES:
            problems.append(
                {"severity": "error", "entity": row["id"], "problem": "invalid external wait state"}
            )
        try:
            deadline = parse_time(row["deadline_at"])
            next_check = parse_time(row["next_check_at"]) if row["next_check_at"] else None
            if next_check and next_check > deadline:
                problems.append(
                    {
                        "severity": "error",
                        "entity": row["id"],
                        "problem": "external wait next check is after its deadline",
                    }
                )
        except (SwarmError, ValueError):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "external wait has an invalid check or deadline timestamp",
                }
            )
        if not row["next_check_at"] and not row["signal_expected"]:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "external wait has no scheduled check or expected signal",
                }
            )
        if row["status"] == "WOKEN" and (
            not row["woke_at"] or row["wake_reason"] not in VALID_WAKE_REASONS
        ):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "woken external wait lacks a valid wake record",
                }
            )
        if row["status"] == "WAITING":
            try:
                deadline_passed = parse_time(row["deadline_at"]) <= now
            except (SwarmError, ValueError):
                deadline_passed = False
            if deadline_passed:
                problems.append(
                    {
                        "severity": "warning",
                        "entity": row["id"],
                        "problem": "external wait deadline has passed and needs reconciliation",
                    }
                )
    for row in conn.execute("SELECT * FROM findings"):
        evidence = json_load(row["evidence_json"], [])
        if row["significance"] not in VALID_FINDING_SIGNIFICANCE:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "invalid finding significance",
                }
            )
        if row["status"] not in VALID_FINDING_STATES:
            problems.append(
                {"severity": "error", "entity": row["id"], "problem": "invalid finding state"}
            )
        if not evidence:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "finding lacks source-backed evidence",
                }
            )
        if row["status"] == "OPEN" and row["significance"] in {"MATERIAL", "URGENT"}:
            problems.append(
                {
                    "severity": "warning",
                    "entity": row["id"],
                    "problem": "%s finding awaits manager disposition"
                    % row["significance"].lower(),
                }
            )
        if row["status"] != "OPEN" and (
            not row["disposition_rationale"] or not row["disposed_by"] or not row["disposed_at"]
        ):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "dispositioned finding lacks rationale, actor, or timestamp",
                }
            )
    for row in conn.execute("SELECT * FROM manager_reviews"):
        if row["status"] not in VALID_MANAGER_REVIEW_STATES:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "invalid manager review state",
                }
            )
        if row["status"] == "RUNNING" and (not row["owner"] or not row["lease_until"]):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "running manager review lacks owner or lease",
                }
            )
        if row["status"] != "RUNNING" and (row["owner"] or row["lease_until"]):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "inactive manager review retains owner or lease",
                }
            )
    for row in conn.execute(
        """SELECT d.id, d.options_json, o.selected_option FROM decision_outcomes o
           JOIN decisions d ON d.id=o.decision_id"""
    ):
        if row["selected_option"] not in json_load(row["options_json"], []):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "structured decision outcome does not match an offered option",
                }
            )
    for row in conn.execute("SELECT * FROM extensions"):
        try:
            validate_extension_manifest(json_load(row["manifest_json"], {}))
        except SwarmError as exc:
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "invalid installed extension: %s" % exc,
                }
            )
    for row in conn.execute("SELECT * FROM deliveries"):
        if row["status"] not in VALID_DELIVERY_STATES:
            problems.append(
                {"severity": "error", "entity": row["id"], "problem": "invalid delivery state"}
            )
        if not delivery_content_intact(dict(row)):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "delivery content is missing or does not match its immutable hash",
                }
            )
        if row["status"] == "CLAIMED" and (not row["claimed_by"] or not row["lease_until"]):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "claimed delivery lacks owner or lease",
                }
            )
        if row["status"] != "CLAIMED" and (row["claimed_by"] or row["lease_until"]):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "unclaimed delivery retains owner or lease",
                }
            )
        if row["status"] == "CLAIMED" and parse_time(row["lease_until"]) < now:
            problems.append(
                {"severity": "warning", "entity": row["id"], "problem": "delivery lease is expired"}
            )
        if row["status"] == "SENT" and (not row["provider_receipt"] or not row["sent_at"]):
            problems.append(
                {
                    "severity": "error",
                    "entity": row["id"],
                    "problem": "sent delivery lacks provider receipt or sent timestamp",
                }
            )
    duplicate_titles = conn.execute(
        "SELECT title, COUNT(*) AS n FROM tasks WHERE status NOT IN ('DONE','CANCELLED') GROUP BY title HAVING COUNT(*) > 1"
    ).fetchall()
    for row in duplicate_titles:
        problems.append(
            {
                "severity": "warning",
                "entity": "tasks",
                "problem": "duplicate active title: %s" % row["title"],
            }
        )
    return {"ok": not any(p["severity"] == "error" for p in problems), "problems": problems}
