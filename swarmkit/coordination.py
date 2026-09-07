"""Durable manager reviews, findings, external waits, and state reconciliation."""

import datetime as dt

from .core import (
    SwarmError,
    VALID_FINDING_SIGNIFICANCE,
    VALID_FINDING_STATES,
    VALID_WAKE_REASONS,
    atomic_write,
    canonical_time,
    completion_outcome,
    future_time,
    json_dump,
    json_load,
    make_id,
    parse_time,
    utcnow,
)
from .queries import external_wait_dict, finding_dict, manager_review_dict
from .storage import (
    add_event,
    all_dependencies_done,
    end_attempt,
    external_wait_row,
    finding_row,
    mission,
    open_decision_count,
    require_active_mission,
    require_owner,
    runtime_state,
    task_row,
    unresolved_ack_count,
    workstream_row,
)


@atomic_write
def reconcile_deliveries(conn, actor="reconciler"):
    now = utcnow()
    rows = conn.execute(
        "SELECT * FROM deliveries WHERE status='CLAIMED' AND lease_until IS NOT NULL AND lease_until < ?",
        (now,),
    ).fetchall()
    changed = []
    for row in rows:
        error = "Delivery lease expired before provider acknowledgment"
        conn.execute(
            """UPDATE deliveries SET status='UNKNOWN', claimed_by=NULL, lease_until=NULL,
               last_error=?, updated_at=? WHERE id=?""",
            (error, now, row["id"]),
        )
        add_event(
            conn,
            row["mission_id"],
            "delivery",
            row["id"],
            "DELIVERY_LEASE_EXPIRED",
            actor,
            {
                "previous_owner": row["claimed_by"],
                "attempt": row["attempt_count"],
            },
        )
        changed.append((row["id"], "UNKNOWN"))
    return changed


@atomic_write
def request_manager_review(conn, reason, entity_type, entity_id, urgency="NORMAL"):
    """Coalesce meaningful changes into one durable, serialized manager review."""
    urgency = urgency.upper()
    if urgency not in {"NORMAL", "URGENT"}:
        raise SwarmError("Manager review urgency must be NORMAL or URGENT")
    current_mission = mission(conn)
    now = utcnow()
    trigger = {
        "reason": reason,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "requested_at": now,
    }
    pending = conn.execute(
        "SELECT * FROM manager_reviews WHERE mission_id=? AND status='PENDING' ORDER BY requested_at LIMIT 1",
        (current_mission["id"],),
    ).fetchone()
    if pending:
        triggers = json_load(pending["triggers_json"], [])
        identity = (reason, entity_type, entity_id)
        if any(
            (item["reason"], item["entity_type"], item["entity_id"]) == identity
            for item in triggers
        ):
            return pending["id"], False
        triggers.append(trigger)
        review_id = pending["id"]
        next_urgency = (
            "URGENT" if urgency == "URGENT" or pending["urgency"] == "URGENT" else "NORMAL"
        )
        conn.execute(
            "UPDATE manager_reviews SET urgency=?, triggers_json=?, updated_at=? WHERE id=?",
            (next_urgency, json_dump(triggers), now, review_id),
        )
    else:
        review_id = make_id("MR")
        conn.execute(
            """INSERT INTO manager_reviews(id, mission_id, urgency, triggers_json,
               requested_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?)""",
            (review_id, current_mission["id"], urgency, json_dump([trigger]), now, now, now),
        )
    add_event(
        conn,
        current_mission["id"],
        "manager_review",
        review_id,
        "MANAGER_REVIEW_REQUESTED",
        "system",
        trigger | {"urgency": urgency},
    )
    return review_id, True


@atomic_write
def reconcile_manager_reviews(conn, actor="reconciler", at=None):
    now = canonical_time(at) if at else utcnow()
    expired = conn.execute(
        """SELECT * FROM manager_reviews WHERE status='RUNNING'
           AND lease_until IS NOT NULL AND lease_until < ?""",
        (now,),
    ).fetchall()
    changed = []
    for row in expired:
        updated = conn.execute(
            """UPDATE manager_reviews SET status='PENDING', owner=NULL, lease_until=NULL,
               started_at=NULL, updated_at=?
               WHERE id=? AND status='RUNNING' AND lease_until=?""",
            (now, row["id"], row["lease_until"]),
        )
        if updated.rowcount != 1:
            continue
        add_event(
            conn,
            row["mission_id"],
            "manager_review",
            row["id"],
            "MANAGER_REVIEW_LEASE_EXPIRED",
            actor,
            {"previous_owner": row["owner"]},
        )
        changed.append((row["id"], "PENDING"))
    return changed


@atomic_write
def claim_manager_review(conn, agent, lease_seconds, debounce_seconds=0):
    now_dt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    due_before = (
        (now_dt - dt.timedelta(seconds=debounce_seconds)).isoformat().replace("+00:00", "Z")
    )
    require_active_mission(conn)
    future_time(lease_seconds)
    reconcile_manager_reviews(conn)
    if (
        conn.execute("SELECT 1 FROM manager_reviews WHERE status='RUNNING'").fetchone()
        or conn.execute(
            "SELECT 1 FROM agent_runs WHERE role='manager' AND ended_at IS NULL"
        ).fetchone()
    ):
        return None
    row = conn.execute(
        """SELECT * FROM manager_reviews WHERE status='PENDING'
           AND (urgency='URGENT' OR requested_at<=?)
           ORDER BY CASE urgency WHEN 'URGENT' THEN 0 ELSE 1 END, requested_at LIMIT 1""",
        (due_before,),
    ).fetchone()
    if not row:
        return None
    lease = (now_dt + dt.timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
    changed = conn.execute(
        """UPDATE manager_reviews SET status='RUNNING', owner=?, started_at=?,
           lease_until=?, updated_at=? WHERE id=? AND status='PENDING'""",
        (agent, utcnow(), lease, utcnow(), row["id"]),
    )
    if changed.rowcount != 1:
        raise SwarmError("Manager review was claimed concurrently")
    conn.execute("DELETE FROM review_commits WHERE review_id=?", (row["id"],))
    add_event(
        conn,
        row["mission_id"],
        "manager_review",
        row["id"],
        "MANAGER_REVIEW_STARTED",
        agent,
        {"lease_until": lease},
    )
    return manager_review_dict(
        conn.execute("SELECT * FROM manager_reviews WHERE id=?", (row["id"],)).fetchone()
    )


@atomic_write
def finish_manager_review(conn, review_id, agent, succeeded):
    row = conn.execute("SELECT * FROM manager_reviews WHERE id=?", (review_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown manager review: %s" % review_id)
    if row["status"] != "RUNNING" or row["owner"] != agent:
        raise SwarmError("Manager review %s is not owned by %s" % (review_id, agent))
    now = utcnow()
    if row["lease_until"] and row["lease_until"] <= now:
        succeeded = False
    if (
        runtime_state(conn)["strict_evidence"]
        and not conn.execute(
            "SELECT 1 FROM review_commits WHERE review_id=?", (review_id,)
        ).fetchone()
    ):
        succeeded = False
    status = "DONE" if succeeded else "PENDING"
    conn.execute(
        """UPDATE manager_reviews SET status=?, owner=NULL, lease_until=NULL,
           completed_at=?, updated_at=? WHERE id=?""",
        (status, now if succeeded else None, now, review_id),
    )
    add_event(
        conn,
        row["mission_id"],
        "manager_review",
        review_id,
        "MANAGER_REVIEW_COMPLETED" if succeeded else "MANAGER_REVIEW_FAILED",
        agent,
        {"status": status},
    )
    if succeeded:
        open_consequential = conn.execute(
            """SELECT significance FROM findings
               WHERE status='OPEN' AND significance IN ('MATERIAL','URGENT')"""
        ).fetchall()
        if open_consequential:
            urgency = (
                "URGENT"
                if any(item["significance"] == "URGENT" for item in open_consequential)
                else "NORMAL"
            )
            request_manager_review(
                conn,
                "consequential finding still needs disposition",
                "mission",
                row["mission_id"],
                urgency,
            )


@atomic_write
def raise_finding(
    conn, task_id, agent, significance, summary, evidence, mission_impact, recommendation=None
):
    task = task_row(conn, task_id)
    require_owner(task, agent)
    significance = significance.upper()
    if significance not in VALID_FINDING_SIGNIFICANCE:
        raise SwarmError("Invalid finding significance: %s" % significance)
    evidence = [item.strip() for item in evidence if item.strip()]
    if not summary.strip() or not evidence or not mission_impact.strip():
        raise SwarmError("A finding requires summary, source-backed evidence, and mission impact")
    finding_id = make_id("FND")
    now = utcnow()
    conn.execute(
        """INSERT INTO findings(id, mission_id, source_task_id, significance, summary,
           evidence_json, mission_impact, recommendation, created_by, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            finding_id,
            task["mission_id"],
            task_id,
            significance,
            summary.strip(),
            json_dump(evidence),
            mission_impact.strip(),
            recommendation.strip() if recommendation else None,
            agent,
            now,
            now,
        ),
    )
    add_event(
        conn,
        task["mission_id"],
        "finding",
        finding_id,
        "FINDING_RAISED",
        agent,
        {
            "source_task_id": task_id,
            "significance": significance,
            "summary": summary.strip(),
            "evidence": evidence,
            "mission_impact": mission_impact.strip(),
            "recommendation": recommendation,
        },
    )
    if significance in {"MATERIAL", "URGENT"}:
        request_manager_review(
            conn,
            "consequential finding raised",
            "finding",
            finding_id,
            "URGENT" if significance == "URGENT" else "NORMAL",
        )
    return finding_id


@atomic_write
def dispose_finding(
    conn, finding_id, disposition, rationale, actor, task_ids=None, workstream_ids=None
):
    row = finding_row(conn, finding_id)
    disposition = disposition.upper()
    if disposition not in VALID_FINDING_STATES - {"OPEN"}:
        raise SwarmError("Finding disposition must be INCORPORATED, DEFERRED, or DISMISSED")
    if row["status"] != "OPEN":
        raise SwarmError("Finding %s is already %s" % (finding_id, row["status"]))
    if not rationale.strip():
        raise SwarmError("Finding disposition requires a rationale")
    task_ids = task_ids or []
    workstream_ids = workstream_ids or []
    for task_id in task_ids:
        task = task_row(conn, task_id)
        if task["mission_id"] != row["mission_id"]:
            raise SwarmError("Resulting task belongs to a different mission")
    for workstream_id in workstream_ids:
        workstream = workstream_row(conn, workstream_id)
        if workstream["mission_id"] != row["mission_id"]:
            raise SwarmError("Resulting workstream belongs to a different mission")
    now = utcnow()
    conn.execute(
        """UPDATE findings SET status=?, disposition_rationale=?, disposed_by=?,
           disposed_at=?, updated_at=? WHERE id=?""",
        (disposition, rationale.strip(), actor, now, now, finding_id),
    )
    for task_id in task_ids:
        conn.execute(
            "INSERT OR IGNORE INTO finding_tasks(finding_id, task_id) VALUES(?,?)",
            (finding_id, task_id),
        )
    for workstream_id in workstream_ids:
        conn.execute(
            "INSERT OR IGNORE INTO finding_workstreams(finding_id, workstream_id) VALUES(?,?)",
            (finding_id, workstream_id),
        )
    add_event(
        conn,
        row["mission_id"],
        "finding",
        finding_id,
        "FINDING_DISPOSITIONED",
        actor,
        {
            "disposition": disposition,
            "rationale": rationale.strip(),
            "resulting_tasks": task_ids,
            "resulting_workstreams": workstream_ids,
        },
    )
    return finding_dict(conn, finding_row(conn, finding_id))


@atomic_write
def start_external_wait(
    conn,
    task_id,
    agent,
    condition,
    external_ref,
    deadline_at,
    next_check_at=None,
    signal_expected=False,
):
    task = task_row(conn, task_id)
    require_owner(task, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError("A resolved decision affecting %s has not been acknowledged" % task_id)
    if not condition.strip() or not external_ref.strip():
        raise SwarmError("External wait requires a condition and external reference")
    if not next_check_at and not signal_expected:
        raise SwarmError("External wait requires --next-check-at or --signal-expected")
    deadline = canonical_time(deadline_at)
    next_check = canonical_time(next_check_at) if next_check_at else None
    now = parse_time(utcnow())
    if parse_time(deadline) <= now:
        raise SwarmError("External wait deadline must be in the future")
    if next_check and parse_time(next_check) <= now:
        raise SwarmError("External wait next check must be in the future")
    if next_check and parse_time(next_check) > parse_time(deadline):
        raise SwarmError("External wait next check may not be after its deadline")
    if conn.execute(
        "SELECT 1 FROM external_waits WHERE task_id=? AND status='WAITING'", (task_id,)
    ).fetchone():
        raise SwarmError("Task %s already has an active external wait" % task_id)
    wait_id = make_id("W")
    recorded_at = utcnow()
    conn.execute(
        """INSERT INTO external_waits(id, mission_id, task_id, condition, external_ref,
           next_check_at, deadline_at, signal_expected, created_by, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            wait_id,
            task["mission_id"],
            task_id,
            condition.strip(),
            external_ref.strip(),
            next_check,
            deadline,
            1 if signal_expected else 0,
            agent,
            recorded_at,
            recorded_at,
        ),
    )
    conn.execute(
        """UPDATE tasks SET status='WAITING_EXTERNAL', owner=NULL, lease_until=NULL,
           next_action=?, updated_at=? WHERE id=?""",
        ("Wait for external condition: %s" % condition.strip(), recorded_at, task_id),
    )
    add_event(
        conn,
        task["mission_id"],
        "external_wait",
        wait_id,
        "EXTERNAL_WAIT_STARTED",
        agent,
        {
            "task_id": task_id,
            "condition": condition.strip(),
            "external_ref": external_ref.strip(),
            "next_check_at": next_check,
            "deadline_at": deadline,
            "signal_expected": bool(signal_expected),
            "generation": task["generation"],
        },
    )
    end_attempt(conn, task_id, "WAITING_EXTERNAL", condition)
    request_manager_review(
        conn, "task released capacity for external wait", "external_wait", wait_id
    )
    return external_wait_dict(conn, external_wait_row(conn, wait_id))


def _wake_external_wait(conn, row, reason, source, external_id, actor, note, at=None):
    if reason not in VALID_WAKE_REASONS:
        raise SwarmError("Invalid external wait wake reason: %s" % reason)
    now = canonical_time(at) if at else utcnow()
    changed = conn.execute(
        """UPDATE external_waits SET status='WOKEN', woke_at=?, wake_reason=?,
           wake_source=?, wake_external_id=?, wake_note=?, updated_at=?
           WHERE id=? AND status='WAITING'""",
        (now, reason, source, external_id, note, now, row["id"]),
    )
    if changed.rowcount != 1:
        return None
    task = task_row(conn, row["task_id"])
    if task["status"] == "WAITING_EXTERNAL":
        if not task["authorized"]:
            next_status = "PROPOSED"
        elif open_decision_count(conn, task["id"]):
            next_status = "BLOCKED"
        elif not all_dependencies_done(conn, task["id"]):
            next_status = "PROPOSED"
        else:
            next_status = "READY"
        conn.execute(
            """UPDATE tasks SET status=?, owner=NULL, lease_until=NULL, next_action=?,
               updated_at=? WHERE id=? AND status='WAITING_EXTERNAL'""",
            (
                next_status,
                "Verify external condition after %s" % reason.lower().replace("_", " "),
                now,
                task["id"],
            ),
        )
        add_event(
            conn,
            task["mission_id"],
            "task",
            task["id"],
            "TASK_WOKEN",
            actor,
            {
                "wait_id": row["id"],
                "wake_reason": reason,
                "external_ref": row["external_ref"],
                "next_status": next_status,
                "verification_required": True,
            },
        )
    add_event(
        conn,
        row["mission_id"],
        "external_wait",
        row["id"],
        "EXTERNAL_WAIT_WOKEN",
        actor,
        {
            "reason": reason,
            "source": source,
            "external_id": external_id,
            "note": note,
            "verification_required": True,
        },
    )
    if reason == "DEADLINE":
        request_manager_review(
            conn, "external wait deadline reached", "external_wait", row["id"], "URGENT"
        )
    return next_status if task["status"] == "WAITING_EXTERNAL" else task["status"]


@atomic_write
def signal_external_wait(conn, wait_id, source, external_id, actor, note=None):
    source = source.strip()
    external_id = external_id.strip()
    if not source or not external_id:
        raise SwarmError("Wait signal requires source and external-id")
    row = external_wait_row(conn, wait_id)
    existing = conn.execute(
        "SELECT * FROM wait_signals WHERE mission_id=? AND source=? AND external_id=?",
        (row["mission_id"], source, external_id),
    ).fetchone()
    created = False
    if existing:
        if existing["wait_id"] != wait_id or (existing["note"] or "") != (note or ""):
            raise SwarmError("Wait signal source/external-id belongs to different input")
    else:
        signal_id = make_id("WSG")
        now = utcnow()
        conn.execute(
            """INSERT INTO wait_signals(id, mission_id, wait_id, source, external_id,
               note, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)""",
            (signal_id, row["mission_id"], wait_id, source, external_id, note, actor, now),
        )
        add_event(
            conn,
            row["mission_id"],
            "wait_signal",
            signal_id,
            "EXTERNAL_WAIT_SIGNAL_RECORDED",
            actor,
            {
                "wait_id": wait_id,
                "source": source,
                "external_id": external_id,
                "note": note,
            },
        )
        created = True
    wake_status = _wake_external_wait(
        conn,
        row,
        "EXTERNAL_SIGNAL",
        source,
        external_id,
        actor,
        note,
    )
    result = external_wait_dict(conn, external_wait_row(conn, wait_id))
    result["signal_created"] = created
    result["woke"] = bool(wake_status)
    return result


@atomic_write
def reconcile_external_waits(conn, actor="reconciler", at=None):
    now = canonical_time(at) if at else utcnow()
    rows = conn.execute(
        """SELECT * FROM external_waits WHERE status='WAITING'
           AND ((next_check_at IS NOT NULL AND next_check_at<=?) OR deadline_at<=?)
           ORDER BY deadline_at, next_check_at""",
        (now, now),
    ).fetchall()
    changed = []
    for row in rows:
        reason = "DEADLINE" if row["deadline_at"] <= now else "SCHEDULED_CHECK"
        next_status = _wake_external_wait(
            conn,
            row,
            reason,
            "scheduler",
            None,
            actor,
            None,
            at=now,
        )
        if next_status:
            changed.append((row["task_id"], next_status))
    return changed


@atomic_write
def reconcile_conn(conn, actor="reconciler", at=None):
    now = canonical_time(at) if at else utcnow()
    changed = reconcile_deliveries(conn, actor)
    changed.extend(reconcile_manager_reviews(conn, actor, at=now))
    expired = conn.execute(
        "SELECT * FROM tasks WHERE status IN ('CLAIMED','RUNNING','VERIFYING') AND lease_until IS NOT NULL AND lease_until < ?",
        (now,),
    ).fetchall()
    for row in expired:
        updated = conn.execute(
            """UPDATE tasks SET status='READY', owner=NULL, lease_until=NULL, updated_at=?
               WHERE id=? AND status=? AND lease_until=?""",
            (now, row["id"], row["status"], row["lease_until"]),
        )
        if updated.rowcount != 1:
            continue
        end_attempt(conn, row["id"], "EXPIRED", "Lease expired")
        conn.execute(
            "UPDATE effects SET state='UNKNOWN',updated_at=? WHERE task_id=? AND generation=? AND state='EXECUTING'",
            (now, row["id"], row["generation"]),
        )
        add_event(
            conn,
            row["mission_id"],
            "task",
            row["id"],
            "TASK_LEASE_EXPIRED",
            actor,
            {"previous_owner": row["owner"], "generation": row["generation"]},
        )
        request_manager_review(conn, "task lease expired", "task", row["id"])
        changed.append((row["id"], "READY"))

    expired_facts = conn.execute(
        "SELECT * FROM facts WHERE status='CURRENT' AND expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    ).fetchall()
    for row in expired_facts:
        conn.execute("UPDATE facts SET status='EXPIRED' WHERE id=?", (row["id"],))
        add_event(
            conn,
            row["mission_id"],
            "fact",
            row["id"],
            "FACT_EXPIRED",
            actor,
            {"subject": row["subject"], "expires_at": row["expires_at"]},
        )
        changed.append((row["id"], "EXPIRED"))

    changed.extend(reconcile_external_waits(conn, actor, at=now))

    candidates = conn.execute(
        "SELECT * FROM tasks WHERE authorized=1 AND status IN ('PROPOSED','BLOCKED')"
    ).fetchall()
    for row in candidates:
        no_open_decisions = open_decision_count(conn, row["id"]) == 0
        dependencies_done = all_dependencies_done(conn, row["id"])
        if no_open_decisions and dependencies_done:
            updated = conn.execute(
                "UPDATE tasks SET status='READY', updated_at=? WHERE id=? AND status=?",
                (now, row["id"], row["status"]),
            )
            if updated.rowcount != 1:
                continue
            event_type = "TASK_UNBLOCKED" if row["status"] == "BLOCKED" else "TASK_READY"
            add_event(conn, row["mission_id"], "task", row["id"], event_type, actor)
            changed.append((row["id"], "READY"))
        elif no_open_decisions and row["status"] == "BLOCKED":
            updated = conn.execute(
                "UPDATE tasks SET status='PROPOSED', updated_at=? WHERE id=? AND status='BLOCKED'",
                (now, row["id"]),
            )
            if updated.rowcount != 1:
                continue
            add_event(conn, row["mission_id"], "task", row["id"], "TASK_DECISION_CLEARED", actor)
            changed.append((row["id"], "PROPOSED"))
    withdrawn = conn.execute(
        """SELECT * FROM decisions d WHERE status='OPEN'
            AND EXISTS (SELECT 1 FROM decision_tasks dt WHERE dt.decision_id=d.id)
            AND NOT EXISTS (SELECT 1 FROM decision_tasks dt JOIN tasks t ON t.id=dt.task_id
                WHERE dt.decision_id=d.id AND t.status NOT IN ('DONE','CANCELLED'))"""
    ).fetchall()
    for decision in withdrawn:
        conn.execute(
            "UPDATE decisions SET status='CANCELLED',updated_at=? WHERE id=?", (now, decision["id"])
        )
        add_event(
            conn,
            decision["mission_id"],
            "decision",
            decision["id"],
            "DECISION_CANCELLED",
            actor,
            {"reason": "All affected work is terminal; no answer is needed"},
        )
        changed.append((decision["id"], "CANCELLED"))
    changed.extend(reconcile_cases(conn, actor))
    return changed


@atomic_write
def reconcile_cases(conn, actor="reconciler"):
    changed = []
    now = utcnow()
    for case in conn.execute(
        "SELECT * FROM cases WHERE status NOT IN ('DONE','CANCELLED')"
    ).fetchall():
        tasks = conn.execute(
            """SELECT t.status, t.result FROM case_tasks ct JOIN tasks t ON t.id=ct.task_id
               WHERE ct.case_id=?""",
            (case["id"],),
        ).fetchall()
        decisions = conn.execute(
            """SELECT DISTINCT d.kind FROM case_tasks ct
               JOIN decision_tasks dt ON dt.task_id=ct.task_id
               JOIN decisions d ON d.id=dt.decision_id
               WHERE ct.case_id=? AND d.status='OPEN'""",
            (case["id"],),
        ).fetchall()
        kinds = {row["kind"] for row in decisions}
        outcome = completion_outcome(row["status"] for row in tasks) if tasks else None
        if tasks and outcome:
            status = "DONE"
        elif kinds & {"human_decision", "missing_access", "safety_stop"}:
            status = "WAITING_HUMAN"
        elif any(row["status"] == "WAITING_EXTERNAL" for row in tasks):
            status = "WAITING_EXTERNAL"
        elif kinds:
            status = "WAITING_EXTERNAL"
        elif not tasks:
            status = "OPEN"
        elif any(row["status"] == "VERIFYING" for row in tasks):
            status = "VERIFYING"
        else:
            status = "ACTIVE"
        if status != case["status"]:
            result_summary = case["result_summary"]
            if status == "DONE":
                results = [
                    row["result"] for row in tasks if row["status"] == "DONE" and row["result"]
                ]
                result_summary = results[-1] if results else "No task result was delivered"
                cancelled = sum(row["status"] == "CANCELLED" for row in tasks)
                if cancelled:
                    result_summary += "; %d task(s) cancelled" % cancelled
            closed_at = now if status in {"DONE", "CANCELLED"} else None
            conn.execute(
                """UPDATE cases SET status=?, result_summary=?, updated_at=?, closed_at=?, completion_outcome=?
                   WHERE id=?""",
                (
                    status,
                    result_summary,
                    now,
                    closed_at,
                    outcome if status == "DONE" else None,
                    case["id"],
                ),
            )
            workstream_status = {
                "OPEN": "ACTIVE",
                "ACTIVE": "ACTIVE",
                "WAITING_HUMAN": "BLOCKED",
                "WAITING_EXTERNAL": "BLOCKED",
                "VERIFYING": "VERIFYING",
                "DONE": "DONE",
                "CANCELLED": "CANCELLED",
            }[status]
            conn.execute(
                """UPDATE workstreams SET status=?, progress_summary=?, updated_at=?, completion_outcome=? WHERE id=?""",
                (
                    workstream_status,
                    result_summary,
                    now,
                    outcome if status == "DONE" else None,
                    case["workstream_id"],
                ),
            )
            add_event(
                conn,
                case["mission_id"],
                "case",
                case["id"],
                "CASE_STATUS_CHANGED",
                actor,
                {
                    "from": case["status"],
                    "to": status,
                    "completion_outcome": outcome if status == "DONE" else None,
                },
            )
            changed.append((case["id"], status))
    return changed


@atomic_write
def commit_review(conn, review_id, agent, dispositions, summary):
    row = conn.execute("SELECT * FROM manager_reviews WHERE id=?", (review_id,)).fetchone()
    if (
        not row
        or row["status"] != "RUNNING"
        or row["owner"] != agent
        or row["lease_until"] <= utcnow()
    ):
        raise SwarmError("Review is not currently leased to this agent")
    triggers = json_load(row["triggers_json"], [])
    if (
        not summary.strip()
        or not isinstance(dispositions, list)
        or len(dispositions) != len(triggers)
    ):
        raise SwarmError("Provide one disposition per trigger, in trigger order, and a summary")
    for item in dispositions:
        if (
            not isinstance(item, dict)
            or item.get("disposition") not in {"acted", "deferred", "no-change"}
            or not item.get("rationale", "").strip()
        ):
            raise SwarmError("Each trigger needs acted/deferred/no-change and a rationale")
    conn.execute(
        "INSERT OR REPLACE INTO review_commits VALUES(?,?,?,?,?)",
        (review_id, agent, json_dump(dispositions), summary, utcnow()),
    )
    add_event(
        conn,
        row["mission_id"],
        "manager_review",
        review_id,
        "MANAGER_REVIEW_COMMITTED",
        agent,
        {"triggers": triggers, "dispositions": dispositions, "summary": summary},
    )
