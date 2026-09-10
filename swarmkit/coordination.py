"""Durable manager reviews, findings, external waits, and state reconciliation."""

import datetime as dt

from .attention import reconcile_attention

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
    has_active_work,
    mission,
    open_decision_count,
    require_active_mission,
    require_owner,
    runtime_state,
    task_row,
    unresolved_ack_count,
    workstream_row,
    publish_review_tasks,
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


MAX_REVIEW_TRIGGERS = 50


@atomic_write
def request_manager_review(conn, reason, entity_type, entity_id, urgency="NORMAL"):
    """Coalesce meaningful changes into bounded, serialized manager reviews."""
    urgency = urgency.upper()
    if urgency not in {"NORMAL", "URGENT"}:
        raise SwarmError("Manager review urgency must be NORMAL or URGENT")
    if not all(
        isinstance(value, str) and value.strip() for value in (reason, entity_type, entity_id)
    ):
        raise SwarmError("Manager review triggers require a reason and entity identity")
    current_mission = mission(conn)
    now = utcnow()
    trigger = {
        "reason": reason,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "requested_at": now,
    }
    duplicate = conn.execute(
        "SELECT mr.id,mr.urgency FROM manager_review_trigger_keys k JOIN manager_reviews mr ON mr.id=k.review_id "
        "WHERE k.reason=? AND k.entity_type=? AND k.entity_id=? AND mr.status='PENDING' "
        "ORDER BY mr.requested_at,mr.rowid LIMIT 1",
        (reason, entity_type, entity_id),
    ).fetchone()
    if duplicate:
        if urgency == "URGENT" and duplicate["urgency"] != "URGENT":
            conn.execute(
                "UPDATE manager_reviews SET urgency='URGENT',updated_at=? WHERE id=?",
                (now, duplicate["id"]),
            )
            add_event(
                conn,
                current_mission["id"],
                "manager_review",
                duplicate["id"],
                "MANAGER_REVIEW_ESCALATED",
                "system",
                trigger,
            )
            return duplicate["id"], True
        return duplicate["id"], False
    pending = conn.execute(
        "SELECT * FROM manager_reviews WHERE status='PENDING' ORDER BY requested_at DESC,rowid DESC LIMIT 1"
    ).fetchone()
    triggers = json_load(pending["triggers_json"], []) if pending else []
    if pending and len(triggers) < MAX_REVIEW_TRIGGERS:
        triggers.append(trigger)
        review_id = pending["id"]
        next_urgency = (
            "URGENT" if urgency == "URGENT" or pending["urgency"] == "URGENT" else "NORMAL"
        )
        conn.execute(
            "UPDATE manager_reviews SET urgency=?,triggers_json=?,updated_at=? WHERE id=?",
            (next_urgency, json_dump(triggers), now, review_id),
        )
    else:
        review_id = make_id("MR")
        conn.execute(
            "INSERT INTO manager_reviews(id,mission_id,urgency,triggers_json,requested_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (review_id, current_mission["id"], urgency, json_dump([trigger]), now, now, now),
        )
    conn.execute(
        "INSERT INTO manager_review_trigger_keys VALUES(?,?,?,?)",
        (review_id, reason, entity_type, entity_id),
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


def review_failed(conn, row, actor, reason, at=None):
    """Close one attempt once; neither urgency nor new triggers erase its retry policy."""
    now = at or utcnow()
    limits = runtime_state(conn)["limits"]
    failures = row["failure_count"] + 1
    maximum = limits.get("max_manager_failures", 3)
    base = limits.get("review_backoff_seconds", 2)
    cap = limits.get("review_backoff_cap_seconds", 300)
    delay = min(base * 2 ** min(failures - 1, 30), cap)
    eligible = (parse_time(now) + dt.timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
    status = "ESCALATED" if failures >= maximum else "PENDING"
    conn.execute(
        "UPDATE manager_reviews SET status=?,owner=NULL,lease_until=NULL,failure_count=?,"
        "next_eligible_at=?,last_error=?,updated_at=? WHERE id=?",
        (status, failures, eligible, reason, now, row["id"]),
    )
    conn.execute(
        "UPDATE review_attempts SET ended_at=?,disposition='FAILED',reason=? "
        "WHERE review_id=? AND generation=? AND ended_at IS NULL",
        (now, reason, row["id"], row["generation"]),
    )
    add_event(
        conn,
        row["mission_id"],
        "manager_review",
        row["id"],
        "MANAGER_REVIEW_FAILED",
        actor,
        {
            "generation": row["generation"],
            "failure_count": failures,
            "next_eligible_at": eligible,
            "reason": reason,
            "status": status,
        },
    )
    if status == "ESCALATED":
        conn.execute("UPDATE runtime_state SET outcome='ESCALATED',reason=? WHERE id=1", (reason,))
        add_event(
            conn,
            row["mission_id"],
            "manager_review",
            row["id"],
            "SUPERVISOR_ESCALATED",
            actor,
            {"reason": reason, "next_action": "Inspect review show, then review retry --reason"},
        )


@atomic_write
def reconcile_manager_reviews(conn, actor="reconciler", at=None):
    now = canonical_time(at) if at else utcnow()
    expired = conn.execute(
        "SELECT * FROM manager_reviews WHERE status='RUNNING' AND lease_until < ?", (now,)
    ).fetchall()
    changed = []
    for row in expired:
        # Retire the lease, but an unfinished process still prevents another claim.
        review_failed(conn, row, actor, "Manager review lease expired", now)
        add_event(
            conn,
            row["mission_id"],
            "manager_review",
            row["id"],
            "MANAGER_REVIEW_LEASE_EXPIRED",
            actor,
            {"previous_owner": row["owner"]},
        )
        changed.append(
            (
                row["id"],
                conn.execute(
                    "SELECT status FROM manager_reviews WHERE id=?", (row["id"],)
                ).fetchone()[0],
            )
        )
    return changed


@atomic_write
def claim_manager_review(
    conn, agent, lease_seconds, debounce_seconds=0, min_interval_seconds=0, max_delay_seconds=60
):
    if conn.execute("SELECT 1 FROM manager_reviews WHERE status='ESCALATED'").fetchone():
        return None
    require_active_mission(conn)
    future_time(lease_seconds)
    reconcile_manager_reviews(conn)
    if conn.execute(
        "SELECT 1 FROM manager_reviews WHERE status IN ('RUNNING','ESCALATED')"
    ).fetchone():
        return None
    if conn.execute(
        "SELECT 1 FROM agent_runs WHERE role='manager' AND ended_at IS NULL"
    ).fetchone():
        return None
    now = utcnow()
    now_dt = parse_time(now)
    due_before = (
        (now_dt - dt.timedelta(seconds=debounce_seconds)).isoformat().replace("+00:00", "Z")
    )
    row = conn.execute(
        "SELECT * FROM manager_reviews WHERE status='PENDING' "
        "AND (next_eligible_at IS NULL OR next_eligible_at<=?) "
        "AND (urgency='URGENT' OR requested_at<=?) "
        "ORDER BY CASE urgency WHEN 'URGENT' THEN 0 ELSE 1 END, requested_at, rowid LIMIT 1",
        (now, due_before),
    ).fetchone()
    if not row:
        return None
    if row["urgency"] != "URGENT" and min_interval_seconds:
        previous = conn.execute(
            "SELECT MAX(completed_at) FROM manager_reviews WHERE status='DONE'"
        ).fetchone()[0]
        ready = conn.execute(
            "SELECT 1 FROM tasks t WHERE status='READY' AND NOT EXISTS "
            "(SELECT 1 FROM staged_tasks s WHERE s.task_id=t.id)"
        ).fetchone()
        age = (now_dt - parse_time(row["requested_at"])).total_seconds()
        if (
            previous
            and ready
            and age < max_delay_seconds
            and (now_dt - parse_time(previous)).total_seconds() < min_interval_seconds
        ):
            return None
    if conn.execute("SELECT 1 FROM review_attempts WHERE agent=?", (agent,)).fetchone():
        raise SwarmError("Use a fresh agent identity for each manager attempt")
    generation = row["generation"] + 1
    lease = future_time(lease_seconds)
    conn.execute(
        "UPDATE manager_reviews SET status='RUNNING',owner=?,started_at=?,lease_until=?,updated_at=?,generation=? WHERE id=?",
        (agent, now, lease, now, generation, row["id"]),
    )
    conn.execute(
        "INSERT INTO review_attempts(review_id,generation,agent,started_at) VALUES(?,?,?,?)",
        (row["id"], generation, agent, now),
    )
    conn.execute("DELETE FROM review_commits WHERE review_id=?", (row["id"],))
    add_event(
        conn,
        row["mission_id"],
        "manager_review",
        row["id"],
        "MANAGER_REVIEW_STARTED",
        agent,
        {"lease_until": lease, "generation": generation},
    )
    return manager_review_dict(
        conn.execute("SELECT * FROM manager_reviews WHERE id=?", (row["id"],)).fetchone()
    )


@atomic_write
def finish_manager_review(conn, review_id, agent, succeeded, failure_reason=None):
    row = conn.execute("SELECT * FROM manager_reviews WHERE id=?", (review_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown manager review: %s" % review_id)
    if row["status"] != "RUNNING" or row["owner"] != agent:
        return False
    if runtime_state(conn)["desired_state"] not in {"ACTIVE", "DRAINING"}:
        return False
    if conn.execute(
        "SELECT 1 FROM agent_runs WHERE agent_id=? AND ended_at IS NULL", (agent,)
    ).fetchone():
        return False
    committed = conn.execute(
        "SELECT 1 FROM review_commits WHERE review_id=? AND actor=?", (review_id, agent)
    ).fetchone()
    if row["lease_until"] <= utcnow():
        succeeded = False
        failure_reason = "Manager review lease expired"
    elif runtime_state(conn)["strict_evidence"] and not committed:
        succeeded = False
        failure_reason = "Manager did not record a semantic review commit"
    if not succeeded:
        review_failed(conn, row, agent, failure_reason or "Manager process failed")
        return False
    now = utcnow()
    conn.execute(
        "UPDATE manager_reviews SET status='DONE',owner=NULL,lease_until=NULL,completed_at=?,"
        "updated_at=?,failure_count=0,next_eligible_at=NULL,last_error=NULL WHERE id=?",
        (now, now, review_id),
    )
    conn.execute(
        "UPDATE review_attempts SET ended_at=?,disposition='SUCCEEDED' WHERE review_id=? AND generation=?",
        (now, review_id, row["generation"]),
    )
    publish_review_tasks(conn, review_id, agent)
    add_event(
        conn,
        row["mission_id"],
        "manager_review",
        review_id,
        "MANAGER_REVIEW_COMPLETED",
        agent,
        {"status": "DONE", "generation": row["generation"]},
    )
    findings = conn.execute(
        "SELECT significance FROM findings WHERE status='OPEN' AND significance IN ('MATERIAL','URGENT')"
    ).fetchall()
    if findings:
        request_manager_review(
            conn,
            "consequential finding still needs disposition",
            "mission",
            row["mission_id"],
            "URGENT" if any(item[0] == "URGENT" for item in findings) else "NORMAL",
        )
    return True


@atomic_write
def retry_manager_review(conn, review_id, actor, reason):
    if not reason.strip():
        raise SwarmError("Review retry requires a reason")
    row = conn.execute("SELECT * FROM manager_reviews WHERE id=?", (review_id,)).fetchone()
    if not row or row["status"] not in {"PENDING", "ESCALATED"}:
        raise SwarmError("Only a pending or escalated review can be retried")
    if conn.execute(
        "SELECT 1 FROM agent_runs WHERE role='manager' AND ended_at IS NULL"
    ).fetchone():
        raise SwarmError("Recover or wait for the previous manager process before retrying")
    conn.execute(
        "UPDATE manager_reviews SET status='PENDING',failure_count=0,next_eligible_at=NULL,last_error=NULL WHERE id=?",
        (review_id,),
    )
    if (
        row["status"] == "ESCALATED"
        and not conn.execute("SELECT 1 FROM manager_reviews WHERE status='ESCALATED'").fetchone()
    ):
        conn.execute(
            "UPDATE runtime_state SET outcome=NULL,reason=NULL WHERE id=1 AND outcome='ESCALATED'"
        )
    add_event(
        conn,
        row["mission_id"],
        "manager_review",
        review_id,
        "MANAGER_REVIEW_RETRIED",
        actor,
        {"reason": reason},
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
    from .commitments import reconcile_commitments

    reconcile_commitments(conn, actor, at=now)

    candidates = conn.execute(
        """SELECT t.id,t.mission_id,t.status,
            NOT EXISTS (SELECT 1 FROM decision_tasks dt JOIN decisions d ON d.id=dt.decision_id
                WHERE dt.task_id=t.id AND d.status='OPEN') AS decisions_clear,
            NOT EXISTS (SELECT 1 FROM task_dependencies td JOIN tasks dependency ON dependency.id=td.depends_on
                WHERE td.task_id=t.id AND dependency.status!='DONE') AS dependencies_clear
            FROM tasks t WHERE t.authorized=1 AND t.status IN ('PROPOSED','BLOCKED')
            AND NOT EXISTS (SELECT 1 FROM staged_tasks s WHERE s.task_id=t.id)"""
    ).fetchall()
    for row in candidates:
        no_open_decisions = row["decisions_clear"]
        dependencies_done = row["dependencies_clear"]
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
    reconcile_attention(conn, actor, now)
    if runtime_state(conn)["desired_state"] == "DRAINING" and not has_active_work(conn):
        conn.execute("UPDATE runtime_state SET desired_state='PAUSED' WHERE id=1")
        mission_id = mission(conn)["id"]
        add_event(
            conn,
            mission_id,
            "mission",
            mission_id,
            "MISSION_DRAINED",
            actor,
            {"desired_state": "PAUSED"},
        )
        changed.append((mission_id, "PAUSED"))
    return changed


@atomic_write
def reconcile_cases(conn, actor="reconciler"):
    changed = []
    now = utcnow()
    # Read counts in one query. Active services should not decode every completed
    # result or issue two additional reads per case on every scheduler poll.
    cases = conn.execute(
        """WITH active_cases AS (
            SELECT id,mission_id,workstream_id,status,result_summary FROM cases
            WHERE status NOT IN ('DONE','CANCELLED')),
        task_counts AS (
            SELECT ct.case_id,COUNT(*) AS total,
                SUM(t.status NOT IN ('DONE','CANCELLED')) AS remaining,
                SUM(t.status='DONE') AS done,SUM(t.status='CANCELLED') AS cancelled,
                SUM(t.status='WAITING_EXTERNAL') AS waiting,SUM(t.status='VERIFYING') AS verifying
            FROM active_cases c JOIN case_tasks ct ON ct.case_id=c.id JOIN tasks t ON t.id=ct.task_id
            GROUP BY ct.case_id),
        decision_counts AS (
            SELECT ct.case_id,COUNT(*) AS open_questions,
                MAX(d.kind IN ('human_decision','missing_access','safety_stop')) AS needs_human
            FROM active_cases c JOIN case_tasks ct ON ct.case_id=c.id
            JOIN decision_tasks dt ON dt.task_id=ct.task_id JOIN decisions d ON d.id=dt.decision_id
            WHERE d.status='OPEN' GROUP BY ct.case_id)
        SELECT c.*,COALESCE(t.total,0) AS total,t.remaining,t.done,t.cancelled,t.waiting,t.verifying,
            d.open_questions,d.needs_human FROM active_cases c
            LEFT JOIN task_counts t ON t.case_id=c.id LEFT JOIN decision_counts d ON d.case_id=c.id"""
    ).fetchall()
    delivery_cases = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT ct.case_id,COUNT(*) FROM commitments c JOIN case_tasks ct ON ct.task_id=c.producer_task WHERE c.status='OPEN' GROUP BY ct.case_id"
        )
    }
    cancelled_delivery_cases = {
        r[0]
        for r in conn.execute(
            "SELECT ct.case_id FROM commitments c JOIN case_tasks ct ON ct.task_id=c.producer_task WHERE c.status='CANCELLED'"
        )
    }
    for case in cases:
        outcome = None
        if delivery_cases.get(case["id"]) and not case["remaining"]:
            status = "WAITING_EXTERNAL"
        elif case["total"] and not case["remaining"]:
            terminal_states = {
                state
                for state, count in (("DONE", case["done"]), ("CANCELLED", case["cancelled"]))
                if count
            }
            if case["id"] in cancelled_delivery_cases:
                terminal_states.add("CANCELLED")
            outcome = completion_outcome(terminal_states)
            status = "DONE"
        elif case["needs_human"]:
            status = "WAITING_HUMAN"
        elif case["waiting"] or case["open_questions"]:
            status = "WAITING_EXTERNAL"
        elif not case["total"]:
            status = "OPEN"
        elif case["verifying"]:
            status = "VERIFYING"
        else:
            status = "ACTIVE"
        if status != case["status"]:
            result_summary = case["result_summary"]
            if status == "DONE":
                last_result = conn.execute(
                    "SELECT t.result FROM tasks t JOIN case_tasks ct ON ct.task_id=t.id "
                    "WHERE ct.case_id=? AND t.status='DONE' AND t.result IS NOT NULL AND t.result!='' "
                    "ORDER BY t.rowid DESC LIMIT 1",
                    (case["id"],),
                ).fetchone()
                result_summary = last_result[0] if last_result else "No task result was delivered"
                if case["cancelled"]:
                    result_summary += "; %d task(s) cancelled" % case["cancelled"]
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
    if runtime_state(conn)["desired_state"] not in {"ACTIVE", "DRAINING"}:
        raise SwarmError("Paused or terminal missions cannot accept a manager review commit")
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
        {
            "triggers": triggers,
            "dispositions": dispositions,
            "summary": summary,
            "staged_commitment_ids": [
                r[0]
                for r in conn.execute(
                    "SELECT id FROM commitments WHERE staged_review=? ORDER BY id", (review_id,)
                )
            ],
            "staged_task_ids": [
                r[0]
                for r in conn.execute(
                    "SELECT task_id FROM staged_tasks WHERE review_id=? ORDER BY task_id",
                    (review_id,),
                )
            ],
        },
    )
