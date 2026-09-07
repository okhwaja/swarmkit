"""Read-only projections of durable state. SQLite remains the source of truth."""

from .core import (
    SwarmError,
    TERMINAL_TASK_STATES,
    canonical_time,
    case_payload_intact,
    delivery_content_intact,
    json_load,
    parse_time,
    utcnow,
)
from .storage import (
    all_dependencies_done,
    budget_reason,
    mission,
    mission_mode,
    open_decision_count,
    runtime_state,
    task_row,
    uncertain_effects,
    unresolved_ack_count,
)


def policy_pack_dict(conn, row, include_guidance=True):
    data = dict(row)
    data["manifest"] = json_load(data.pop("manifest_json"), {})
    if not include_guidance:
        data.pop("guidance_text", None)
    return data


def policy_pack_summary(conn, row):
    pack = policy_pack_dict(conn, row, include_guidance=False)
    manifest = pack["manifest"]
    return {
        "id": pack["id"],
        "version": pack["version"],
        "name": pack["name"],
        "description": pack["description"],
        "when_to_use": pack["when_to_use"],
        "variables": manifest.get("variables", {}),
        "stages": [
            {"id": stage["id"], "kind": stage["kind"], "title": stage["title"]}
            for stage in manifest.get("stages", [])
        ],
        "installed_at": pack["installed_at"],
    }


def policy_application_dict(conn, application_id, include_definition=False):
    row = conn.execute("SELECT * FROM policy_applications WHERE id=?", (application_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown policy application: %s" % application_id)
    data = dict(row)
    data["variables"] = json_load(data.pop("variables_json"), {})
    manifest = json_load(data.pop("manifest_json"), {})
    guidance = data.pop("guidance_text", "")
    if include_definition:
        data["manifest"] = manifest
        data["guidance_text"] = guidance
    tasks = [
        dict(item)
        for item in conn.execute(
            """SELECT pat.stage_id, pat.task_id, pat.fresh_session_from, t.title, t.kind,
           t.status, t.owner, t.result FROM policy_application_tasks pat
           JOIN tasks t ON t.id=pat.task_id WHERE pat.application_id=?
           ORDER BY t.created_at""",
            (application_id,),
        )
    ]
    for task in tasks:
        task["fresh_session_from"] = json_load(task["fresh_session_from"], [])
    data["tasks"] = tasks
    if tasks and all(item["status"] == "DONE" for item in tasks):
        data["status"] = "DONE"
    elif any(item["status"] == "BLOCKED" for item in tasks):
        data["status"] = "BLOCKED"
    elif all(item["status"] in TERMINAL_TASK_STATES for item in tasks):
        data["status"] = "CANCELLED"
    else:
        data["status"] = "ACTIVE"
    return data


def policy_context_for_task(conn, task_id):
    link = conn.execute(
        """SELECT pat.application_id, pat.stage_id, pat.fresh_session_from,
           pa.policy_id, pa.policy_version, pa.variables_json,
           pa.guidance_text, pa.manifest_json FROM policy_application_tasks pat
           JOIN policy_applications pa ON pa.id=pat.application_id
           WHERE pat.task_id=?""",
        (task_id,),
    ).fetchone()
    if not link:
        return None
    data = dict(link)
    manifest = json_load(data.pop("manifest_json"), {})
    data["name"] = manifest.get("name", data["policy_id"])
    data["variables"] = json_load(data.pop("variables_json"), {})
    data["fresh_session_from"] = json_load(data["fresh_session_from"], [])
    data["stage"] = next(
        (stage for stage in manifest.get("stages", []) if stage.get("id") == data["stage_id"]), None
    )
    return data


def extension_dict(row, include_guidance=True):
    data = dict(row)
    data["handles"] = json_load(data.pop("handles_json"), [])
    data["manifest"] = json_load(data.pop("manifest_json"), {})
    if not include_guidance:
        data.pop("guidance_text", None)
    return data


def extension_summary(row):
    extension = extension_dict(row, include_guidance=False)
    return {
        "id": extension["id"],
        "version": extension["version"],
        "name": extension["name"],
        "kind": extension["kind"],
        "description": extension["description"],
        "handles": extension["handles"],
        "executor_type": extension["manifest"]["executor"]["type"],
        "installed_at": extension["installed_at"],
    }


def delivery_dict(conn, row):
    data = dict(row)
    data["recipients"] = json_load(data.pop("recipients_json"), [])
    data["metadata"] = json_load(data.pop("metadata_json"), {})
    data["extension_manifest"] = json_load(data.pop("extension_manifest_json"), {})
    data.pop("extension_guidance_text", None)
    data["content_intact"] = delivery_content_intact(data)
    data["runs"] = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM delivery_runs WHERE delivery_id=? ORDER BY started_at", (row["id"],)
        )
    ]
    return data


def manager_review_dict(row):
    data = dict(row)
    data["triggers"] = json_load(data.pop("triggers_json"), [])
    end = parse_time(data["completed_at"]) if data["completed_at"] else parse_time(utcnow())
    data["age_seconds"] = max(0, int((end - parse_time(data["requested_at"])).total_seconds()))
    return data


def finding_dict(conn, row):
    data = dict(row)
    data["evidence"] = json_load(data.pop("evidence_json"), [])
    age_end = parse_time(data["disposed_at"]) if data["disposed_at"] else parse_time(utcnow())
    data["age_seconds"] = max(0, int((age_end - parse_time(data["created_at"])).total_seconds()))
    data["resulting_tasks"] = [
        item["task_id"]
        for item in conn.execute(
            "SELECT task_id FROM finding_tasks WHERE finding_id=? ORDER BY task_id", (row["id"],)
        )
    ]
    data["resulting_workstreams"] = [
        item["workstream_id"]
        for item in conn.execute(
            "SELECT workstream_id FROM finding_workstreams WHERE finding_id=? ORDER BY workstream_id",
            (row["id"],),
        )
    ]
    return data


def external_wait_dict(conn, row, at=None):
    data = dict(row)
    data["signal_expected"] = bool(data["signal_expected"])
    now = parse_time(canonical_time(at) if at else utcnow())
    end = parse_time(data["woke_at"]) if data["woke_at"] else now
    data["waiting_seconds"] = max(0, int((end - parse_time(data["created_at"])).total_seconds()))
    data["overdue"] = data["status"] == "WAITING" and parse_time(data["deadline_at"]) <= now
    task = task_row(conn, data["task_id"])
    data["task_status"] = task["status"]
    data["requires_attention"] = (
        data["wake_reason"] == "DEADLINE" and task["status"] not in TERMINAL_TASK_STATES
    )
    data["signals"] = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM wait_signals WHERE wait_id=? ORDER BY created_at", (row["id"],)
        )
    ]
    return data


def signal_dict(row):
    data = dict(row)
    data["metadata"] = json_load(data.pop("metadata_json"), {})
    data["payload_intact"] = case_payload_intact(
        data["payload_path"], data["payload_sha256"], data["payload_size_bytes"]
    )
    return data


def case_dict(conn, row):
    data = dict(row)
    data["metadata"] = json_load(data.pop("metadata_json"), {})
    data["payload_intact"] = case_payload_intact(
        data["payload_path"], data["payload_sha256"], data["payload_size_bytes"]
    )
    data["tasks"] = [
        dict(item)
        for item in conn.execute(
            """SELECT t.id, t.title, t.kind, t.status, t.owner, t.next_action, t.result,
           t.created_at, t.updated_at FROM case_tasks ct JOIN tasks t ON t.id=ct.task_id
           WHERE ct.case_id=? ORDER BY t.rowid""",
            (row["id"],),
        )
    ]
    data["signals"] = [
        signal_dict(item)
        for item in conn.execute(
            "SELECT * FROM case_signals WHERE case_id=? ORDER BY created_at", (row["id"],)
        )
    ]
    data["open_decisions"] = [
        decision_dict(conn, item)
        for item in conn.execute(
            """SELECT DISTINCT d.* FROM case_tasks ct
           JOIN decision_tasks dt ON dt.task_id=ct.task_id
           JOIN decisions d ON d.id=dt.decision_id
           WHERE ct.case_id=? AND d.status='OPEN' ORDER BY d.created_at""",
            (row["id"],),
        )
    ]
    return data


def case_summary(conn, row):
    case = dict(row)
    decisions = [
        dict(item)
        for item in conn.execute(
            """SELECT DISTINCT d.id, d.kind, d.question, d.recommendation
           FROM case_tasks ct JOIN decision_tasks dt ON dt.task_id=ct.task_id
           JOIN decisions d ON d.id=dt.decision_id
           WHERE ct.case_id=? AND d.status='OPEN' ORDER BY d.created_at""",
            (case["id"],),
        )
    ]
    task_counts = {
        item["status"]: item["n"]
        for item in conn.execute(
            """SELECT t.status, COUNT(*) AS n FROM case_tasks ct JOIN tasks t ON t.id=ct.task_id
           WHERE ct.case_id=? GROUP BY t.status""",
            (case["id"],),
        )
    }
    return {
        "id": case["id"],
        "source": case["source"],
        "external_id": case["external_id"],
        "title": case["title"],
        "objective": case["objective"],
        "status": case["status"],
        "priority": case["priority"],
        "workstream_id": case["workstream_id"],
        "policy_application_id": case["policy_application_id"],
        "result_summary": case["result_summary"],
        "task_counts": task_counts,
        "open_decisions": decisions,
        "updated_at": case["updated_at"],
        "closed_at": case["closed_at"],
    }


def task_dict(conn, row, include_responsive_history=True):
    data = dict(row)
    data["authorized"] = bool(data["authorized"])
    data["acceptance"] = json_load(data.pop("acceptance_json"), [])
    data["verification"] = json_load(data.pop("verification_json"), [])
    data["depends_on"] = [
        r["depends_on"]
        for r in conn.execute(
            "SELECT depends_on FROM task_dependencies WHERE task_id=? ORDER BY depends_on",
            (row["id"],),
        )
    ]
    data["decisions"] = [
        r["decision_id"]
        for r in conn.execute(
            "SELECT decision_id FROM decision_tasks WHERE task_id=? ORDER BY decision_id",
            (row["id"],),
        )
    ]
    data["case_ids"] = [
        r["case_id"]
        for r in conn.execute(
            "SELECT case_id FROM case_tasks WHERE task_id=? ORDER BY case_id", (row["id"],)
        )
    ]
    wait_rows = conn.execute(
        "SELECT * FROM external_waits WHERE task_id=? ORDER BY created_at", (row["id"],)
    ).fetchall()
    finding_rows = conn.execute(
        "SELECT * FROM findings WHERE source_task_id=? ORDER BY created_at", (row["id"],)
    ).fetchall()
    if include_responsive_history:
        data["external_waits"] = [external_wait_dict(conn, item) for item in wait_rows]
        data["findings"] = [finding_dict(conn, item) for item in finding_rows]
    else:
        data["external_wait_ids"] = [item["id"] for item in wait_rows]
        data["finding_ids"] = [item["id"] for item in finding_rows]
    workstream = conn.execute(
        "SELECT workstream_id FROM task_workstreams WHERE task_id=?", (row["id"],)
    ).fetchone()
    data["workstream_id"] = workstream["workstream_id"] if workstream else None
    data["artifacts"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM artifacts WHERE task_id=? ORDER BY created_at", (row["id"],)
        )
    ]
    data["policy"] = policy_context_for_task(conn, row["id"])
    return data


def decision_dict(conn, row):
    data = dict(row)
    data["options"] = json_load(data.pop("options_json"), [])
    data["blocks"] = [
        r["task_id"]
        for r in conn.execute(
            "SELECT task_id FROM decision_tasks WHERE decision_id=? ORDER BY task_id", (row["id"],)
        )
    ]
    data["acknowledgments"] = [
        dict(r)
        for r in conn.execute(
            "SELECT task_id, version, agent_id, acknowledged_at FROM decision_acks WHERE decision_id=? ORDER BY task_id",
            (row["id"],),
        )
    ]
    outcome = conn.execute(
        "SELECT selected_option FROM decision_outcomes WHERE decision_id=?", (row["id"],)
    ).fetchone()
    data["selected_option"] = outcome["selected_option"] if outcome else None
    return data


def workstream_dict(conn, row):
    data = dict(row)
    tasks = [
        dict(r)
        for r in conn.execute(
            """SELECT t.id, t.title, t.status, t.kind, t.owner, t.last_checkpoint_at
           FROM task_workstreams tw JOIN tasks t ON t.id=tw.task_id
           WHERE tw.workstream_id=? ORDER BY t.priority DESC, t.created_at""",
            (row["id"],),
        )
    ]
    counts = {}
    for task in tasks:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    decisions = [
        dict(r)
        for r in conn.execute(
            """SELECT DISTINCT d.id, d.kind, d.question, d.status, d.recommendation
           FROM task_workstreams tw
           JOIN decision_tasks dt ON dt.task_id=tw.task_id
           JOIN decisions d ON d.id=dt.decision_id
           WHERE tw.workstream_id=? ORDER BY d.created_at""",
            (row["id"],),
        )
    ]
    data["tasks"] = tasks
    data["task_counts"] = counts
    data["open_decisions"] = [decision for decision in decisions if decision["status"] == "OPEN"]
    data["needs_human"] = [
        decision
        for decision in data["open_decisions"]
        if decision["kind"] in {"human_decision", "missing_access", "safety_stop"}
    ]
    return data


def mission_snapshot(conn):
    m = dict(mission(conn))
    m["mode"] = mission_mode(conn)
    m["success"] = json_load(m.pop("success_json"), [])
    m["constraints"] = json_load(m.pop("constraints_json"), [])
    tasks = [
        task_dict(conn, r, include_responsive_history=False)
        for r in conn.execute("SELECT * FROM tasks ORDER BY priority DESC, created_at")
    ]
    workstreams = [
        workstream_dict(conn, r)
        for r in conn.execute("SELECT * FROM workstreams ORDER BY created_at")
    ]
    decisions = [
        decision_dict(conn, r) for r in conn.execute("SELECT * FROM decisions ORDER BY created_at")
    ]
    artifacts = [dict(r) for r in conn.execute("SELECT * FROM artifacts ORDER BY created_at")]
    facts = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM facts ORDER BY CASE status WHEN 'CURRENT' THEN 0 ELSE 1 END, subject, observed_at DESC"
        )
    ]
    policies = [
        policy_pack_summary(conn, r) for r in conn.execute("SELECT * FROM policy_packs ORDER BY id")
    ]
    policy_applications = [
        policy_application_dict(conn, r["id"])
        for r in conn.execute("SELECT id FROM policy_applications ORDER BY created_at")
    ]
    cases = [
        case_summary(conn, r)
        for r in conn.execute("SELECT * FROM cases ORDER BY priority DESC, created_at")
    ]
    findings = [
        finding_dict(conn, r)
        for r in conn.execute(
            "SELECT * FROM findings ORDER BY CASE significance WHEN 'URGENT' THEN 0 WHEN 'MATERIAL' THEN 1 ELSE 2 END, created_at"
        )
    ]
    external_waits = [
        external_wait_dict(conn, r)
        for r in conn.execute("SELECT * FROM external_waits ORDER BY created_at")
    ]
    manager_reviews = [
        manager_review_dict(r)
        for r in conn.execute("SELECT * FROM manager_reviews ORDER BY requested_at")
    ]
    extensions = [
        extension_summary(r) for r in conn.execute("SELECT * FROM extensions ORDER BY id")
    ]
    deliveries = [
        delivery_dict(conn, r) for r in conn.execute("SELECT * FROM deliveries ORDER BY created_at")
    ]
    return {
        "mission": m,
        "workstreams": workstreams,
        "tasks": tasks,
        "decisions": decisions,
        "facts": facts,
        "artifacts": artifacts,
        "policies": policies,
        "policy_applications": policy_applications,
        "cases": cases,
        "findings": findings,
        "external_waits": external_waits,
        "manager_reviews": manager_reviews,
        "extensions": extensions,
        "deliveries": deliveries,
        "runtime": runtime_state(conn),
    }


def explain_state(conn):
    state = runtime_state(conn)
    tasks = []
    for row in conn.execute(
        "SELECT * FROM tasks WHERE status NOT IN ('DONE','CANCELLED') ORDER BY priority DESC, id"
    ):
        reasons = []
        if state["desired_state"] != "ACTIVE":
            reasons.append("Mission " + state["desired_state"])
        if not row["authorized"]:
            reasons.append("Manager authorization required")
        if not all_dependencies_done(conn, row["id"]):
            reasons.append("Dependencies incomplete")
        if open_decision_count(conn, row["id"]):
            reasons.append("Human decision pending")
        if unresolved_ack_count(conn, row["id"]):
            reasons.append("Current decision must be acknowledged")
        if uncertain_effects(conn, row["id"]):
            reasons.append("External effect requires reconciliation")
        limit = budget_reason(conn, row["id"])
        if limit:
            reasons.append(limit)
        if row["status"] == "WAITING_EXTERNAL":
            reasons.append("Durable external wait; inspect wait list")
        tasks.append(
            {
                "task_id": row["id"],
                "status": row["status"],
                "reasons": reasons,
                "next_action": row["next_action"],
                "checkpoint": row["checkpoint_summary"],
            }
        )
    return {
        "runtime": state,
        "tasks": tasks,
        "uncertain_effects": [dict(r) for r in uncertain_effects(conn)],
        "unfinished_runs": [
            dict(r) for r in conn.execute("SELECT * FROM agent_runs WHERE ended_at IS NULL")
        ],
        "unfinished_delivery_runs": [
            dict(r) for r in conn.execute("SELECT * FROM delivery_runs WHERE ended_at IS NULL")
        ],
        "uncertain_deliveries": [
            dict(r)
            for r in conn.execute(
                "SELECT id,subject,status,last_error FROM deliveries WHERE status='UNKNOWN'"
            )
        ],
        "attempts": [
            dict(r) for r in conn.execute("SELECT * FROM attempts ORDER BY started_at,id")
        ],
        "event_watermark": conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0],
    }


def workspace_dict(row):
    result = dict(row)
    # Keep the legacy branch column for old consumers; generic clients use workspace_ref.
    result["workspace_ref"] = result["branch"]
    return result
