"""Check database consistency and report actionable integrity problems."""

import datetime as dt

from .core import consistent_read
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
from .storage import mission, mission_mode


@consistent_read
def doctor(conn):
    problems = []

    def report(severity, entity, message):
        problems.append({"severity": severity, "entity": entity, "problem": message})

    def read_time(value, entity, field):
        try:
            return parse_time(value)
        except (SwarmError, ValueError, TypeError, AttributeError):
            report("error", entity, "invalid " + field + " timestamp")
            return None

    def read_json(value, default, entity, field):
        try:
            decoded = json_load(value, default)
            if not isinstance(decoded, type(default)):
                raise ValueError("unexpected JSON type")
            return decoded
        except (ValueError, TypeError):
            report("error", entity, "invalid " + field + " JSON")
            return default

    now = dt.datetime.now(dt.timezone.utc)
    current_mission = mission(conn)
    if mission_mode(conn) not in VALID_MISSION_MODES:
        report("error", current_mission["id"], "invalid mission mode")
    for row in conn.execute(
        """WITH waits AS (
            SELECT task_id,COUNT(*) AS total FROM external_waits WHERE status='WAITING' GROUP BY task_id)
        SELECT t.id,t.status,t.owner,t.lease_until,t.verification_json,COALESCE(w.total,0) AS active_waits,
            EXISTS(SELECT 1 FROM task_workstreams tw WHERE tw.task_id=t.id) AS linked,
            EXISTS(SELECT 1 FROM decision_tasks dt JOIN decisions d ON d.id=dt.decision_id
                WHERE dt.task_id=t.id AND d.status='OPEN') AS has_open_decision
        FROM tasks t LEFT JOIN waits w ON w.task_id=t.id"""
    ):
        if row["status"] not in VALID_TASK_STATES:
            report("error", row["id"], "invalid task state")
        if row["status"] in ACTIVE_TASK_STATES and not row["owner"]:
            report("error", row["id"], "active task has no owner")
        if row["status"] in ACTIVE_TASK_STATES and not row["lease_until"]:
            report("error", row["id"], "active task has no lease")
        lease = (
            read_time(row["lease_until"], row["id"], "task lease") if row["lease_until"] else None
        )
        if lease and lease < now and row["status"] in ACTIVE_TASK_STATES:
            report("warning", row["id"], "task lease is expired")
        if row["status"] == "DONE" and not read_json(
            row["verification_json"], [], row["id"], "task verification"
        ):
            report("error", row["id"], "done task lacks verification")
        if row["status"] == "BLOCKED" and not row["has_open_decision"]:
            report("warning", row["id"], "blocked task has no open decision")
        active_waits = row["active_waits"]
        if row["status"] == "WAITING_EXTERNAL" and active_waits != 1:
            report("error", row["id"], "externally waiting task must have exactly one active wait")
        if row["status"] != "WAITING_EXTERNAL" and active_waits:
            report(
                "error", row["id"], "active external wait belongs to a task not in WAITING_EXTERNAL"
            )
        if row["status"] == "WAITING_EXTERNAL" and (row["owner"] or row["lease_until"]):
            report("error", row["id"], "externally waiting task retains owner or lease")
        if current_mission["phase"] != "DISCOVERY" and not row["linked"]:
            report("warning", row["id"], "task is not assigned to an executive workstream")
    for row in conn.execute(
        """WITH counts AS (
            SELECT tw.workstream_id,COUNT(*) AS total,
                SUM(t.status NOT IN ('DONE','CANCELLED')) AS remaining,
                SUM(t.status IN ('CLAIMED','RUNNING','VERIFYING')) AS active
            FROM task_workstreams tw JOIN tasks t ON t.id=tw.task_id GROUP BY tw.workstream_id)
        SELECT w.id,w.status,w.progress_summary,w.forecast_latest,
            COALESCE(c.total,0) AS total,COALESCE(c.remaining,0) AS remaining,COALESCE(c.active,0) AS active
        FROM workstreams w LEFT JOIN counts c ON c.workstream_id=w.id"""
    ):
        if row["status"] in {"ACTIVE", "BLOCKED", "VERIFYING"} and not row["progress_summary"]:
            report("warning", row["id"], "active workstream lacks a progress summary")
        if row["status"] == "PLANNED" and (row["active"] or 0):
            report("warning", row["id"], "planned workstream has active tasks")
        if (
            row["status"] in {"ACTIVE", "BLOCKED", "VERIFYING"}
            and row["total"]
            and not row["remaining"]
        ):
            report(
                "warning", row["id"], "all linked tasks are terminal but workstream is not closed"
            )
        latest = (
            read_time(row["forecast_latest"], row["id"], "workstream forecast")
            if row["forecast_latest"]
            else None
        )
        if row["status"] not in {"DONE", "CANCELLED"} and latest and latest < now:
            report(
                "warning",
                row["id"],
                "latest forecast has passed; update the forecast and rationale",
            )
        if row["status"] in {"DONE", "CANCELLED"} and row["remaining"]:
            report("error", row["id"], row["status"].lower() + " workstream has non-terminal tasks")
    for row in conn.execute(
        "SELECT id,task_id,state FROM workspace_creations WHERE state IN ('UNKNOWN','CREATED')"
    ):
        report(
            "warning",
            row["task_id"],
            "checkout creation "
            + row["id"]
            + " needs "
            + (
                "provider reconciliation"
                if row["state"] == "UNKNOWN"
                else "attachment with workspace create"
            ),
        )
    for row in conn.execute("SELECT * FROM policy_packs"):
        try:
            validate_policy_manifest(
                read_json(row["manifest_json"], {}, row["id"], "policy manifest")
            )
        except SwarmError as exc:
            report("error", row["id"], "invalid installed policy: %s" % exc)
    for row in conn.execute("SELECT * FROM policy_applications"):
        manifest = read_json(row["manifest_json"], {}, row["id"], "policy application manifest")
        try:
            validate_policy_manifest(manifest)
        except SwarmError as exc:
            report("error", row["id"], "invalid policy application: %s" % exc)
            continue
        expected = {stage["id"] for stage in manifest.get("stages", [])}
        actual = {
            item["stage_id"]
            for item in conn.execute(
                "SELECT stage_id FROM policy_application_tasks WHERE application_id=?", (row["id"],)
            )
        }
        if expected != actual:
            report(
                "error", row["id"], "policy application stages do not match its manifest snapshot"
            )
    for row in conn.execute(
        """SELECT c.id,c.status,c.payload_path,c.payload_sha256,c.payload_size_bytes,
            EXISTS(SELECT 1 FROM case_tasks ct LEFT JOIN task_workstreams tw ON tw.task_id=ct.task_id
                WHERE ct.case_id=c.id AND (tw.workstream_id IS NULL OR tw.workstream_id!=c.workstream_id)) AS mismatched
        FROM cases c"""
    ):
        if row["status"] not in VALID_CASE_STATES:
            report("error", row["id"], "invalid case state")
        if not case_payload_intact(
            row["payload_path"], row["payload_sha256"], row["payload_size_bytes"]
        ):
            report(
                "error",
                row["id"],
                "initial case payload is missing or does not match its immutable hash",
            )
        if row["mismatched"]:
            report("error", row["id"], "case tasks are missing or assigned to another workstream")
    for row in conn.execute("SELECT * FROM case_signals"):
        if not case_payload_intact(
            row["payload_path"], row["payload_sha256"], row["payload_size_bytes"]
        ):
            report(
                "error",
                row["id"],
                "case signal payload is missing or does not match its immutable hash",
            )
    for row in conn.execute("SELECT * FROM external_waits"):
        if row["status"] not in VALID_WAIT_STATES:
            report("error", row["id"], "invalid external wait state")
        deadline = read_time(row["deadline_at"], row["id"], "external wait deadline")
        next_check = (
            read_time(row["next_check_at"], row["id"], "external wait check")
            if row["next_check_at"]
            else None
        )
        if next_check and deadline and next_check > deadline:
            report("error", row["id"], "external wait next check is after its deadline")
        if not row["next_check_at"] and not row["signal_expected"]:
            report("error", row["id"], "external wait has no scheduled check or expected signal")
        if row["status"] == "WOKEN" and (
            not row["woke_at"] or row["wake_reason"] not in VALID_WAKE_REASONS
        ):
            report("error", row["id"], "woken external wait lacks a valid wake record")
        if row["status"] == "WAITING" and deadline and deadline <= now:
            report(
                "warning", row["id"], "external wait deadline has passed and needs reconciliation"
            )
    for row in conn.execute("SELECT * FROM findings"):
        evidence = read_json(row["evidence_json"], [], row["id"], "finding evidence")
        if row["significance"] not in VALID_FINDING_SIGNIFICANCE:
            report("error", row["id"], "invalid finding significance")
        if row["status"] not in VALID_FINDING_STATES:
            report("error", row["id"], "invalid finding state")
        if not evidence:
            report("error", row["id"], "finding lacks source-backed evidence")
        if row["status"] == "OPEN" and row["significance"] in {"MATERIAL", "URGENT"}:
            report(
                "warning",
                row["id"],
                "%s finding awaits manager disposition" % row["significance"].lower(),
            )
        if row["status"] != "OPEN" and (
            not row["disposition_rationale"] or not row["disposed_by"] or not row["disposed_at"]
        ):
            report("error", row["id"], "dispositioned finding lacks rationale, actor, or timestamp")
    for row in conn.execute("SELECT * FROM manager_reviews"):
        if row["status"] == "ESCALATED":
            report(
                "warning",
                row["id"],
                "Manager retries stopped; inspect review show and repair before review retry",
            )
        if row["status"] not in VALID_MANAGER_REVIEW_STATES:
            report("error", row["id"], "invalid manager review state")
        if row["status"] == "RUNNING" and (not row["owner"] or not row["lease_until"]):
            report("error", row["id"], "running manager review lacks owner or lease")
        if row["status"] != "RUNNING" and (row["owner"] or row["lease_until"]):
            report("error", row["id"], "inactive manager review retains owner or lease")
    for row in conn.execute(
        """SELECT d.id, d.options_json, o.selected_option FROM decision_outcomes o
           JOIN decisions d ON d.id=o.decision_id"""
    ):
        if row["selected_option"] not in read_json(
            row["options_json"], [], row["id"], "decision options"
        ):
            report(
                "error", row["id"], "structured decision outcome does not match an offered option"
            )
    for row in conn.execute("SELECT * FROM extensions"):
        try:
            validate_extension_manifest(
                read_json(row["manifest_json"], {}, row["id"], "extension manifest")
            )
        except SwarmError as exc:
            report("error", row["id"], "invalid installed extension: %s" % exc)
    for row in conn.execute("SELECT * FROM deliveries"):
        if row["status"] not in VALID_DELIVERY_STATES:
            report("error", row["id"], "invalid delivery state")
        if not delivery_content_intact(dict(row)):
            report(
                "error",
                row["id"],
                "delivery content is missing or does not match its immutable hash",
            )
        if row["status"] == "CLAIMED" and (not row["claimed_by"] or not row["lease_until"]):
            report("error", row["id"], "claimed delivery lacks owner or lease")
        if row["status"] != "CLAIMED" and (row["claimed_by"] or row["lease_until"]):
            report("error", row["id"], "unclaimed delivery retains owner or lease")
        lease = (
            read_time(row["lease_until"], row["id"], "delivery lease")
            if row["lease_until"]
            else None
        )
        if row["status"] == "CLAIMED" and lease and lease < now:
            report("warning", row["id"], "delivery lease is expired")
        if row["status"] == "SENT" and (not row["provider_receipt"] or not row["sent_at"]):
            report("error", row["id"], "sent delivery lacks provider receipt or sent timestamp")
    duplicate_titles = conn.execute(
        """SELECT t.title,tw.workstream_id,COUNT(*) AS n FROM tasks t
           LEFT JOIN task_workstreams tw ON tw.task_id=t.id WHERE t.status NOT IN ('DONE','CANCELLED')
           GROUP BY tw.workstream_id,t.title HAVING COUNT(*) > 1"""
    ).fetchall()
    for row in duplicate_titles:
        report(
            "warning",
            row["workstream_id"] or "tasks",
            "duplicate active title in this workstream: %s" % row["title"],
        )
    return {"ok": not any(p["severity"] == "error" for p in problems), "problems": problems}
