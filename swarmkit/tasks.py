"""Mission and task lifecycle, workstreams, planning limits, and facts."""

from pathlib import Path
import datetime as dt

from .coordination import reconcile_conn, request_manager_review
from .core import (
    ACTIVE_TASK_STATES,
    SwarmError,
    TERMINAL_TASK_STATES,
    VALID_BLOCKER_KINDS,
    VALID_FORECAST_CONFIDENCE,
    VALID_TASK_KINDS,
    VALID_WORKSTREAM_STATES,
    atomic_write,
    canonical_time,
    json_dump,
    json_load,
    make_id,
    parse_time,
    utcnow,
)
from .evidence import evidence_gaps
from .queries import policy_context_for_task
from .storage import (
    add_event,
    attempt_for_task,
    budget_reason,
    end_attempt,
    mission,
    mission_mode,
    register_artifact,
    require_active_mission,
    require_owner,
    runtime_state,
    task_row,
    uncertain_effects,
    unresolved_ack_count,
    workstream_row,
)


@atomic_write
def add_workstream(conn, name, outcome, actor, status="PLANNED"):
    status = status.upper()
    if status not in VALID_WORKSTREAM_STATES:
        raise SwarmError("Invalid workstream status: %s" % status)
    m = mission(conn)
    if m["status"] == "DONE":
        raise SwarmError("Cannot add a workstream to a completed mission")
    workstream_id = make_id("WS")
    now = utcnow()
    conn.execute(
        """INSERT INTO workstreams(id, mission_id, name, outcome, status, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?)""",
        (workstream_id, m["id"], name, outcome, status, now, now),
    )
    add_event(
        conn,
        m["id"],
        "workstream",
        workstream_id,
        "WORKSTREAM_CREATED",
        actor,
        {
            "name": name,
            "outcome": outcome,
            "status": status,
        },
    )
    return workstream_id


@atomic_write
def update_workstream(
    conn,
    workstream_id,
    actor,
    status=None,
    summary=None,
    forecast_earliest=None,
    forecast_latest=None,
    forecast_confidence=None,
    forecast_basis=None,
):
    row = workstream_row(conn, workstream_id)
    next_status = status.upper() if status else row["status"]
    if next_status not in VALID_WORKSTREAM_STATES:
        raise SwarmError("Invalid workstream status: %s" % next_status)
    if row["status"] in {"DONE", "CANCELLED"} and next_status != row["status"]:
        raise SwarmError("Terminal workstream %s cannot be reopened" % workstream_id)
    confidence = forecast_confidence.lower() if forecast_confidence else row["forecast_confidence"]
    if confidence and confidence not in VALID_FORECAST_CONFIDENCE:
        raise SwarmError("Invalid forecast confidence: %s" % confidence)
    earliest = canonical_time(forecast_earliest) if forecast_earliest else row["forecast_earliest"]
    latest = canonical_time(forecast_latest) if forecast_latest else row["forecast_latest"]
    if earliest and latest and parse_time(earliest) > parse_time(latest):
        raise SwarmError("Forecast earliest time must not be after latest time")
    if (earliest or latest) and not (forecast_basis or row["forecast_basis"]):
        raise SwarmError("A forecast requires a basis")
    if not any(
        value is not None
        for value in (
            status,
            summary,
            forecast_earliest,
            forecast_latest,
            forecast_confidence,
            forecast_basis,
        )
    ):
        raise SwarmError("No workstream update was supplied")
    if next_status == "DONE":
        remaining = conn.execute(
            """SELECT COUNT(*) AS n FROM task_workstreams tw JOIN tasks t ON t.id=tw.task_id
               WHERE tw.workstream_id=? AND t.status NOT IN ('DONE','CANCELLED')""",
            (workstream_id,),
        ).fetchone()["n"]
        if remaining:
            raise SwarmError(
                "Cannot complete workstream while %d linked tasks are non-terminal" % remaining
            )
    next_summary = summary if summary is not None else row["progress_summary"]
    next_basis = forecast_basis if forecast_basis is not None else row["forecast_basis"]
    now = utcnow()
    conn.execute(
        """UPDATE workstreams SET status=?, progress_summary=?, forecast_earliest=?,
           forecast_latest=?, forecast_confidence=?, forecast_basis=?, updated_at=? WHERE id=?""",
        (next_status, next_summary, earliest, latest, confidence, next_basis, now, workstream_id),
    )
    add_event(
        conn,
        row["mission_id"],
        "workstream",
        workstream_id,
        "WORKSTREAM_UPDATED",
        actor,
        {
            "status": next_status,
            "progress_summary": next_summary,
            "forecast_earliest": earliest,
            "forecast_latest": latest,
            "forecast_confidence": confidence,
            "forecast_basis": next_basis,
        },
    )


@atomic_write
def link_task_workstream(conn, workstream_id, task_id, actor):
    workstream = workstream_row(conn, workstream_id)
    task = task_row(conn, task_id)
    if workstream["mission_id"] != task["mission_id"]:
        raise SwarmError("Task and workstream belong to different missions")
    if workstream["status"] in {"DONE", "CANCELLED"} and task["status"] not in TERMINAL_TASK_STATES:
        raise SwarmError("Cannot link active task to terminal workstream %s" % workstream_id)
    prior = conn.execute(
        "SELECT workstream_id FROM task_workstreams WHERE task_id=?", (task_id,)
    ).fetchone()
    conn.execute(
        """INSERT INTO task_workstreams(task_id, workstream_id) VALUES(?,?)
           ON CONFLICT(task_id) DO UPDATE SET workstream_id=excluded.workstream_id""",
        (task_id, workstream_id),
    )
    add_event(
        conn,
        task["mission_id"],
        "workstream",
        workstream_id,
        "TASK_LINKED_TO_WORKSTREAM",
        actor,
        {
            "task_id": task_id,
            "previous_workstream_id": prior["workstream_id"] if prior else None,
        },
    )
    return not prior or prior["workstream_id"] != workstream_id


def verify_dependencies_exist(conn, task_ids):
    for dep in task_ids:
        task_row(conn, dep)


@atomic_write
def add_task(
    conn,
    title,
    description,
    kind,
    acceptance,
    depends_on,
    priority,
    actor,
    ready,
    workstream_id=None,
    idempotency_key=None,
):
    if kind not in VALID_TASK_KINDS:
        raise SwarmError("Invalid task kind: %s" % kind)
    specification = json_dump(
        [title, description, kind, acceptance, depends_on, priority, ready, workstream_id]
    )
    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM plan_keys WHERE key=?", (idempotency_key,)
        ).fetchone()
        if existing:
            if existing["specification"] != specification:
                raise SwarmError("Planning key reused with different task specification")
            return existing["task_id"]
    limits = runtime_state(conn)["limits"]
    if (
        limits.get("max_tasks")
        and conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= limits["max_tasks"]
    ):
        raise SwarmError("Task quota exhausted")
    verify_dependencies_exist(conn, depends_on)
    m = mission(conn)
    if m["status"] == "DONE" or runtime_state(conn)["desired_state"] in {"CANCELLED", "ABANDONED"}:
        raise SwarmError("Cannot add a task to a terminal mission")
    if workstream_id:
        workstream = workstream_row(conn, workstream_id)
        if workstream["mission_id"] != m["id"]:
            raise SwarmError("Workstream belongs to a different mission")
        if workstream["status"] in {"DONE", "CANCELLED"}:
            raise SwarmError("Cannot add a task to terminal workstream %s" % workstream_id)
    task_id = make_id("T")
    now = utcnow()
    conn.execute(
        """INSERT INTO tasks(id, mission_id, title, description, kind, priority, authorized,
           acceptance_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id,
            m["id"],
            title,
            description,
            kind,
            priority,
            1 if ready else 0,
            json_dump(acceptance),
            now,
            now,
        ),
    )
    for dep in depends_on:
        conn.execute(
            "INSERT INTO task_dependencies(task_id, depends_on) VALUES(?,?)", (task_id, dep)
        )
    if workstream_id:
        conn.execute(
            "INSERT INTO task_workstreams(task_id, workstream_id) VALUES(?,?)",
            (task_id, workstream_id),
        )
    add_event(
        conn,
        m["id"],
        "task",
        task_id,
        "TASK_PROPOSED",
        actor,
        {
            "title": title,
            "kind": kind,
            "acceptance": acceptance,
            "depends_on": depends_on,
            "authorized": bool(ready),
            "priority": priority,
            "workstream_id": workstream_id,
        },
    )
    if idempotency_key:
        conn.execute(
            "INSERT INTO plan_keys VALUES(?,?,?)", (idempotency_key, specification, task_id)
        )
    reconcile_conn(conn, actor="system")
    return task_id


@atomic_write
def approve_task(conn, task_id, actor):
    row = task_row(conn, task_id)
    if row["status"] in TERMINAL_TASK_STATES:
        raise SwarmError("Cannot approve terminal task %s" % task_id)
    conn.execute(
        "UPDATE tasks SET authorized = 1, updated_at = ? WHERE id = ?", (utcnow(), task_id)
    )
    add_event(conn, row["mission_id"], "task", task_id, "TASK_AUTHORIZED", actor)
    reconcile_conn(conn, actor="system")


@atomic_write
def claim_task(conn, task_id, agent, lease_seconds):
    reconcile_conn(conn)
    state = require_active_mission(conn)
    if lease_seconds <= 0:
        raise SwarmError("Lease duration must be positive")
    row = task_row(conn, task_id)
    reason = budget_reason(conn, task_id)
    if reason:
        raise SwarmError(reason)
    if uncertain_effects(conn, task_id):
        raise SwarmError("Reconcile uncertain effects before reclaiming task")
    if conn.execute(
        "SELECT 1 FROM attempts WHERE task_id=? AND agent=?", (task_id, agent)
    ).fetchone():
        raise SwarmError("Use a fresh agent identity for each attempt")
    if row["status"] != "READY":
        raise SwarmError("Task %s is %s, not READY" % (task_id, row["status"]))
    unfinished_run = conn.execute(
        "SELECT id FROM agent_runs WHERE task_id=? AND ended_at IS NULL ORDER BY started_at LIMIT 1",
        (task_id,),
    ).fetchone()
    if unfinished_run:
        raise SwarmError(
            "Task %s still has active harness run %s" % (task_id, unfinished_run["id"])
        )
    policy_stage = conn.execute(
        "SELECT application_id, fresh_session_from FROM policy_application_tasks WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if policy_stage and policy_stage["fresh_session_from"]:
        for prior_stage in json_load(policy_stage["fresh_session_from"], []):
            prior = conn.execute(
                """SELECT task_id FROM policy_application_tasks
                   WHERE application_id=? AND stage_id=?""",
                (policy_stage["application_id"], prior_stage),
            ).fetchone()
            completion = (
                conn.execute(
                    """SELECT actor FROM events WHERE entity_id=? AND event_type='TASK_COMPLETED'
                   ORDER BY seq DESC LIMIT 1""",
                    (prior["task_id"],),
                ).fetchone()
                if prior
                else None
            )
            if not completion:
                raise SwarmError(
                    "Task %s requires completed policy stage %s" % (task_id, prior_stage)
                )
            if completion["actor"] == agent:
                raise SwarmError(
                    "Task %s requires a fresh agent identity distinct from policy stage %s"
                    % (task_id, prior_stage)
                )
    now_dt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    lease = (now_dt + dt.timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
    generation = row["generation"] + 1
    changed = conn.execute(
        """UPDATE tasks SET status='CLAIMED', owner=?, lease_until=?, generation=?, updated_at=?
           WHERE id=? AND status='READY'""",
        (agent, lease, generation, utcnow(), task_id),
    )
    if changed.rowcount != 1:
        raise SwarmError("Task %s was claimed concurrently" % task_id)
    add_event(
        conn,
        row["mission_id"],
        "task",
        task_id,
        "TASK_CLAIMED",
        agent,
        {"generation": generation, "lease_until": lease},
    )
    conn.execute(
        "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,NULL,NULL)",
        (make_id("ATT"), task_id, generation, agent, "RUNNING", state["revision"], utcnow()),
    )
    return generation


@atomic_write
def checkpoint_task(conn, task_id, agent, summary, next_action, lease_seconds):
    row = task_row(conn, task_id)
    require_owner(row, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError("A resolved decision affecting %s has not been acknowledged" % task_id)
    now_dt = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    lease = (now_dt + dt.timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
    now = utcnow()
    conn.execute(
        """UPDATE tasks SET status='RUNNING', checkpoint_summary=?, next_action=?,
           last_checkpoint_at=?, lease_until=?, updated_at=? WHERE id=?""",
        (summary, next_action, now, lease, now, task_id),
    )
    add_event(
        conn,
        row["mission_id"],
        "task",
        task_id,
        "TASK_CHECKPOINTED",
        agent,
        {
            "summary": summary,
            "next_action": next_action,
            "generation": row["generation"],
        },
    )


@atomic_write
def complete_task(conn, task_id, agent, result, verification, artifacts):
    row = task_row(conn, task_id)
    require_owner(row, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError(
            "Resolved decisions affecting %s must be acknowledged before completion" % task_id
        )
    if uncertain_effects(conn, task_id):
        raise SwarmError("Cannot complete with uncertain external effects")
    attempt = attempt_for_task(conn, task_id)
    if attempt and attempt["mission_revision"] != runtime_state(conn)["revision"]:
        raise SwarmError("Attempt belongs to an obsolete mission revision")
    if (
        runtime_state(conn)["strict_evidence"]
        or conn.execute("SELECT 1 FROM task_contracts WHERE task_id=?", (task_id,)).fetchone()
    ):
        gaps = evidence_gaps(conn, task_id)
        if gaps:
            raise SwarmError("Missing current evidence: " + "; ".join(gaps))
    if not verification:
        raise SwarmError("At least one verification statement is required")
    policy = policy_context_for_task(conn, task_id)
    completion = policy["stage"].get("completion", {}) if policy and policy.get("stage") else {}
    minimum_artifacts = completion.get("minimum_artifacts", 0)
    if len(artifacts) < minimum_artifacts:
        raise SwarmError(
            "Policy stage requires at least %d artifact(s); received %d"
            % (minimum_artifacts, len(artifacts))
        )
    if completion.get("artifact_files_required"):
        missing = [value for value in artifacts if not Path(value).expanduser().resolve().is_file()]
        if missing:
            raise SwarmError(
                "Policy stage artifacts must be existing files: %s" % ", ".join(missing)
            )
    verification_text = "\n".join(verification).lower()
    missing_terms = [
        term
        for term in completion.get("verification_terms", [])
        if term.lower() not in verification_text
    ]
    if missing_terms:
        raise SwarmError("Policy stage verification must mention: %s" % ", ".join(missing_terms))
    now = utcnow()
    conn.execute(
        """UPDATE tasks SET status='DONE', result=?, verification_json=?, owner=NULL,
           lease_until=NULL, next_action=NULL, updated_at=? WHERE id=?""",
        (result, json_dump(verification), now, task_id),
    )
    artifact_ids = []
    for value in artifacts:
        artifact_ids.append(register_artifact(conn, task_id, value, actor=agent))
    add_event(
        conn,
        row["mission_id"],
        "task",
        task_id,
        "TASK_COMPLETED",
        agent,
        {
            "result": result,
            "verification": verification,
            "artifacts": artifact_ids,
            "generation": row["generation"],
        },
    )
    end_attempt(conn, task_id, "SUCCEEDED")
    request_manager_review(conn, "task completed", "task", task_id)
    reconcile_conn(conn)


@atomic_write
def cancel_task(conn, task_id, actor, reason):
    row = task_row(conn, task_id)
    if row["status"] in TERMINAL_TASK_STATES:
        raise SwarmError("Task is already terminal")
    conn.execute(
        "UPDATE tasks SET status='CANCELLED', owner=NULL, lease_until=NULL, result=?, updated_at=? WHERE id=?",
        (reason, utcnow(), task_id),
    )
    active_waits = conn.execute(
        "SELECT * FROM external_waits WHERE task_id=? AND status='WAITING'", (task_id,)
    ).fetchall()
    for wait in active_waits:
        conn.execute(
            "UPDATE external_waits SET status='CANCELLED', updated_at=? WHERE id=?",
            (utcnow(), wait["id"]),
        )
        add_event(
            conn,
            row["mission_id"],
            "external_wait",
            wait["id"],
            "EXTERNAL_WAIT_CANCELLED",
            actor,
            {"task_id": task_id, "reason": reason},
        )
    end_attempt(conn, task_id, "CANCELLED", reason)
    add_event(conn, row["mission_id"], "task", task_id, "TASK_CANCELLED", actor, {"reason": reason})
    descendants = conn.execute(
        """WITH RECURSIVE children(id) AS (
        SELECT task_id FROM task_dependencies WHERE depends_on=?
        UNION SELECT d.task_id FROM task_dependencies d JOIN children c ON d.depends_on=c.id)
        SELECT t.* FROM tasks t JOIN children c ON t.id=c.id WHERE t.status NOT IN ('DONE','CANCELLED')""",
        (task_id,),
    ).fetchall()
    for child in descendants:
        end_attempt(conn, child["id"], "CANCELLED", "Dependency cancelled: " + task_id)
        conn.execute(
            "UPDATE tasks SET status='CANCELLED',owner=NULL,lease_until=NULL,result=?,updated_at=? WHERE id=?",
            ("Dependency cancelled: " + task_id, utcnow(), child["id"]),
        )
        conn.execute(
            "UPDATE external_waits SET status='CANCELLED',updated_at=? WHERE task_id=? AND status='WAITING'",
            (utcnow(), child["id"]),
        )
        add_event(
            conn,
            child["mission_id"],
            "task",
            child["id"],
            "TASK_DEPENDENCY_CANCELLED",
            actor,
            {"dependency": task_id, "reason": reason},
        )


@atomic_write
def block_task(conn, task_id, agent, kind, question, recommendation, options):
    if kind not in VALID_BLOCKER_KINDS:
        raise SwarmError("Invalid blocker kind: %s" % kind)
    row = task_row(conn, task_id)
    require_owner(row, agent)
    decision_id = make_id("D")
    now = utcnow()
    conn.execute(
        """INSERT INTO decisions(id, mission_id, kind, question, recommendation, options_json,
           requested_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            decision_id,
            row["mission_id"],
            kind,
            question,
            recommendation,
            json_dump(options),
            task_id,
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO decision_tasks(decision_id, task_id) VALUES(?,?)", (decision_id, task_id)
    )
    conn.execute(
        "UPDATE tasks SET status='BLOCKED', owner=NULL, lease_until=NULL, next_action=?, updated_at=? WHERE id=?",
        ("Await decision %s" % decision_id, now, task_id),
    )
    add_event(
        conn,
        row["mission_id"],
        "decision",
        decision_id,
        "DECISION_REQUESTED",
        agent,
        {
            "kind": kind,
            "question": question,
            "recommendation": recommendation,
            "options": options,
            "blocks": [task_id],
        },
    )
    end_attempt(conn, task_id, "WAITING_HUMAN", question)
    return decision_id


@atomic_write
def record_fact(
    conn,
    subject,
    value,
    source,
    actor,
    task_id=None,
    observed_at=None,
    expires_at=None,
    ttl_seconds=None,
):
    m = mission(conn)
    if task_id:
        task_row(conn, task_id)
    observed = canonical_time(observed_at) if observed_at else utcnow()
    observed_dt = parse_time(observed)
    if expires_at and ttl_seconds is not None:
        raise SwarmError("Use either expires_at or ttl_seconds, not both")
    expiry = canonical_time(expires_at) if expires_at else None
    if ttl_seconds is not None:
        expiry = (
            (observed_dt + dt.timedelta(seconds=ttl_seconds))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    if expiry and parse_time(expiry) <= observed_dt:
        raise SwarmError("Fact expiry must be after its observation time")
    fact_id = make_id("F")
    now = utcnow()
    prior = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM facts WHERE subject=? AND status='CURRENT'", (subject,)
        )
    ]
    conn.execute(
        "UPDATE facts SET status='SUPERSEDED' WHERE subject=? AND status='CURRENT'", (subject,)
    )
    conn.execute(
        """INSERT INTO facts(id, mission_id, task_id, subject, value, source, observed_at,
           expires_at, recorded_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (fact_id, m["id"], task_id, subject, value, source, observed, expiry, actor, now),
    )
    add_event(
        conn,
        m["id"],
        "fact",
        fact_id,
        "FACT_RECORDED",
        actor,
        {
            "subject": subject,
            "value": value,
            "source": source,
            "observed_at": observed,
            "expires_at": expiry,
            "task_id": task_id,
            "supersedes": prior,
        },
    )
    return fact_id


@atomic_write
def set_mission_phase(conn, phase, actor):
    phase = phase.upper()
    if phase not in {"DISCOVERY", "EXECUTION", "VERIFICATION", "RECOVERY"}:
        raise SwarmError("Invalid mission phase")
    m = mission(conn)
    conn.execute("UPDATE missions SET phase=?, updated_at=? WHERE id=?", (phase, utcnow(), m["id"]))
    add_event(conn, m["id"], "mission", m["id"], "MISSION_PHASE_CHANGED", actor, {"phase": phase})


@atomic_write
def complete_mission(conn, evidence, actor, shutdown_service=False):
    m = mission(conn)
    if runtime_state(conn)["desired_state"] not in {"ACTIVE", "DRAINING"}:
        raise SwarmError("Mission must be active or draining to complete")
    if uncertain_effects(conn):
        raise SwarmError("Reconcile uncertain effects before mission completion")
    if mission_mode(conn) == "SERVICE" and not shutdown_service:
        raise SwarmError(
            "SERVICE missions stay active when idle; pass --shutdown-service to terminate deliberately"
        )
    active = conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE status NOT IN ('DONE','CANCELLED')"
    ).fetchone()["n"]
    if active:
        raise SwarmError("Cannot complete mission while %d tasks are non-terminal" % active)
    consequential = conn.execute(
        """SELECT COUNT(*) AS n FROM findings
           WHERE significance IN ('MATERIAL','URGENT') AND status='OPEN'"""
    ).fetchone()["n"]
    if consequential:
        raise SwarmError(
            "Cannot complete mission while %d material or urgent findings lack disposition"
            % consequential
        )
    active_workstreams = conn.execute(
        "SELECT COUNT(*) AS n FROM workstreams WHERE status NOT IN ('DONE','CANCELLED')"
    ).fetchone()["n"]
    if active_workstreams:
        raise SwarmError(
            "Cannot complete mission while %d workstreams are non-terminal" % active_workstreams
        )
    if not evidence.strip():
        raise SwarmError("Mission completion requires evidence")
    conn.execute(
        "UPDATE missions SET status='DONE', completion_evidence=?, updated_at=? WHERE id=?",
        (evidence, utcnow(), m["id"]),
    )
    conn.execute("UPDATE runtime_state SET outcome='SUCCEEDED' WHERE id=1")
    add_event(conn, m["id"], "mission", m["id"], "MISSION_COMPLETED", actor, {"evidence": evidence})


@atomic_write
def control_mission(conn, action, actor, reason):
    state = runtime_state(conn)
    transitions = {
        "pause": "PAUSED",
        "drain": "DRAINING",
        "resume": "ACTIVE",
        "cancel": "CANCELLED",
        "abandon": "ABANDONED",
    }
    if action not in transitions:
        raise SwarmError("Unknown lifecycle action")
    if not reason.strip():
        raise SwarmError("Lifecycle changes require a reason")
    if state["desired_state"] in {"CANCELLED", "ABANDONED"} or mission(conn)["status"] == "DONE":
        raise SwarmError("Terminal missions cannot resume; create a new mission")
    if action == "resume" and uncertain_effects(conn):
        raise SwarmError("Reconcile uncertain effects before resuming")
    if (
        action == "resume"
        and conn.execute("SELECT 1 FROM agent_runs WHERE ended_at IS NULL").fetchone()
    ):
        raise SwarmError("Wait for active harnesses or run recover before resuming")
    desired = transitions[action]
    if (
        action == "drain"
        and not conn.execute(
            "SELECT 1 FROM tasks WHERE status IN ('CLAIMED','RUNNING','VERIFYING')"
        ).fetchone()
        and not conn.execute("SELECT 1 FROM agent_runs WHERE ended_at IS NULL").fetchone()
    ):
        desired = "PAUSED"
    if action in {"pause", "cancel", "abandon"}:
        for task in conn.execute(
            "SELECT * FROM tasks WHERE status NOT IN ('DONE','CANCELLED')"
        ).fetchall():
            if action != "pause" or task["status"] in ACTIVE_TASK_STATES:
                end_attempt(
                    conn, task["id"], "CANCELLED" if action != "pause" else "INTERRUPTED", reason
                )
                status = "CANCELLED" if action != "pause" else "READY"
                conn.execute(
                    "UPDATE tasks SET status=?,owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                    (status, utcnow(), task["id"]),
                )
        conn.execute(
            "UPDATE effects SET state='UNKNOWN',updated_at=? WHERE state='EXECUTING'", (utcnow(),)
        )
    if action in {"cancel", "abandon"}:
        conn.execute(
            "UPDATE external_waits SET status='CANCELLED',updated_at=? WHERE status='WAITING'",
            (utcnow(),),
        )
        conn.execute(
            "UPDATE deliveries SET status='CANCELLED',updated_at=? WHERE status='PENDING'",
            (utcnow(),),
        )
        conn.execute(
            "UPDATE cases SET status='CANCELLED',updated_at=? WHERE status NOT IN ('DONE','CANCELLED')",
            (utcnow(),),
        )
        conn.execute(
            "UPDATE workstreams SET status='CANCELLED',updated_at=? WHERE status NOT IN ('DONE','CANCELLED')",
            (utcnow(),),
        )
    outcome = "CANCELLED" if action == "cancel" else ("ESCALATED" if action == "abandon" else None)
    conn.execute(
        "UPDATE runtime_state SET desired_state=?,outcome=?,reason=? WHERE id=1",
        (desired, outcome, reason),
    )
    add_event(
        conn,
        mission(conn)["id"],
        "mission",
        mission(conn)["id"],
        "MISSION_CONTROLLED",
        actor,
        {
            "action": action,
            "desired_state": desired,
            "reason": reason,
            "cleanup": "Harnesses may still be running; inspect recover and uncertain effects.",
        },
    )
    return runtime_state(conn)


@atomic_write
def configure_runtime(conn, limits, strict_evidence=None, actor="human"):
    allowed = {"max_attempts_per_task", "max_tasks", "max_runs", "deadline"}
    if set(limits) - allowed:
        raise SwarmError("Unknown limit; supported: %s" % ", ".join(sorted(allowed)))
    for key, value in limits.items():
        if key == "deadline":
            limits[key] = canonical_time(value)
        elif not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SwarmError("Limits must be positive integers")
    state = runtime_state(conn)
    state["limits"].update(limits)
    conn.execute(
        "UPDATE runtime_state SET limits_json=?,strict_evidence=? WHERE id=1",
        (
            json_dump(state["limits"]),
            state["strict_evidence"] if strict_evidence is None else int(strict_evidence),
        ),
    )
    add_event(
        conn,
        mission(conn)["id"],
        "mission",
        mission(conn)["id"],
        "RUNTIME_CONFIGURED",
        actor,
        {"limits": state["limits"], "strict_evidence": strict_evidence},
    )
    return runtime_state(conn)


@atomic_write
def amend_mission(conn, objective, success, constraints, reason, actor):
    state = runtime_state(conn)
    if state["desired_state"] != "PAUSED":
        raise SwarmError("Pause the mission before amending it")
    if conn.execute(
        "SELECT 1 FROM agent_runs WHERE ended_at IS NULL"
    ).fetchone() or uncertain_effects(conn):
        raise SwarmError("Drain/recover harnesses and reconcile effects before amendment")
    if not objective.strip() or not reason.strip():
        raise SwarmError("Amendment requires objective and rationale")
    previous = dict(mission(conn))
    new = {"objective": objective, "success": success, "constraints": constraints}
    revision = state["revision"] + 1
    conn.execute(
        "INSERT INTO mission_amendments VALUES(?,?,?,?,?,?)",
        (revision, json_dump(previous), json_dump(new), reason, actor, utcnow()),
    )
    conn.execute(
        "UPDATE missions SET objective=?,success_json=?,constraints_json=?,updated_at=? WHERE id=?",
        (objective, json_dump(success), json_dump(constraints), utcnow(), previous["id"]),
    )
    conn.execute("UPDATE runtime_state SET revision=? WHERE id=1", (revision,))
    # A revised objective requires the manager to explicitly adopt remaining work.
    conn.execute("UPDATE tasks SET authorized=0 WHERE status NOT IN ('DONE','CANCELLED')")
    conn.execute("UPDATE tasks SET status='PROPOSED' WHERE status='READY'")
    request_manager_review(conn, "mission amended", "mission", previous["id"], "URGENT")
    add_event(
        conn,
        previous["id"],
        "mission",
        previous["id"],
        "MISSION_AMENDED",
        actor,
        {"revision": revision, "reason": reason},
    )
    return {"revision": revision}
