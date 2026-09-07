"""Versioned decisions and acknowledgement of changed instructions."""

from .coordination import reconcile_conn
from .core import SwarmError, TERMINAL_TASK_STATES, atomic_write, json_load, utcnow
from .storage import (
    add_event,
    cancel_external_waits,
    decision_row,
    end_attempt,
    require_owner,
    task_row,
)


def validate_decision_choice(row, choice):
    if choice is None:
        return None
    choice = choice.strip()
    options = json_load(row["options_json"], [])
    if not choice:
        raise SwarmError("Decision choice may not be empty")
    if choice not in options:
        raise SwarmError("Decision choice must exactly match one option: %s" % ", ".join(options))
    return choice


def require_decision_choice(conn, decision_id, choice):
    row = decision_row(conn, decision_id)
    if row["status"] != "RESOLVED":
        raise SwarmError("Decision %s is not resolved" % decision_id)
    outcome = conn.execute(
        "SELECT selected_option FROM decision_outcomes WHERE decision_id=?", (decision_id,)
    ).fetchone()
    if not outcome:
        raise SwarmError("Decision %s has no structured selected option" % decision_id)
    if outcome["selected_option"] != choice:
        raise SwarmError(
            "Decision %s selected %s, not required choice %s"
            % (decision_id, outcome["selected_option"], choice)
        )
    return {
        "authorized": True,
        "decision_id": decision_id,
        "selected_option": outcome["selected_option"],
        "version": row["version"],
        "decided_by": row["decided_by"],
        "decided_at": row["decided_at"],
    }


@atomic_write
def resolve_decision(conn, decision_id, answer, actor, choice=None):
    if not answer.strip():
        raise SwarmError("Decision answer must not be empty")
    row = decision_row(conn, decision_id)
    if row["status"] != "OPEN":
        raise SwarmError("Decision %s is already %s" % (decision_id, row["status"]))
    selected_option = validate_decision_choice(row, choice)
    now = utcnow()
    version = row["version"] + 1
    changed = conn.execute(
        """UPDATE decisions SET status='RESOLVED', answer=?, decided_by=?, decided_at=?,
           version=?, updated_at=? WHERE id=? AND status='OPEN'""",
        (answer, actor, now, version, now, decision_id),
    )
    if changed.rowcount != 1:
        raise SwarmError("Decision %s was resolved concurrently" % decision_id)
    if selected_option:
        conn.execute(
            "INSERT INTO decision_outcomes(decision_id, selected_option) VALUES(?,?)",
            (decision_id, selected_option),
        )
    blocked = [
        r["task_id"]
        for r in conn.execute(
            "SELECT task_id FROM decision_tasks WHERE decision_id=?", (decision_id,)
        )
    ]
    add_event(
        conn,
        row["mission_id"],
        "decision",
        decision_id,
        "DECISION_RESOLVED",
        actor,
        {
            "answer": answer,
            "selected_option": selected_option,
            "version": version,
            "affected_tasks": blocked,
        },
    )
    reconcile_conn(conn)
    return version


@atomic_write
def revise_decision(conn, decision_id, answer, actor, choice=None):
    if not answer.strip():
        raise SwarmError("Decision answer must not be empty")
    row = decision_row(conn, decision_id)
    if row["status"] != "RESOLVED":
        raise SwarmError("Decision %s must be resolved before it can be revised" % decision_id)
    selected_option = validate_decision_choice(row, choice)
    now = utcnow()
    version = row["version"] + 1
    conn.execute(
        "UPDATE decisions SET answer=?, decided_by=?, decided_at=?, version=?, updated_at=? WHERE id=?",
        (answer, actor, now, version, now, decision_id),
    )
    conn.execute("DELETE FROM decision_outcomes WHERE decision_id=?", (decision_id,))
    if selected_option:
        conn.execute(
            "INSERT INTO decision_outcomes(decision_id, selected_option) VALUES(?,?)",
            (decision_id, selected_option),
        )
    affected = [
        r["task_id"]
        for r in conn.execute(
            "SELECT task_id FROM decision_tasks WHERE decision_id=?", (decision_id,)
        )
    ]
    for task_id in affected:
        task = task_row(conn, task_id)
        if task["status"] not in TERMINAL_TASK_STATES and task["authorized"]:
            end_attempt(conn, task_id, "INTERRUPTED", "Decision revised: " + decision_id)
            cancel_external_waits(conn, task_id, actor, "Decision revised: " + decision_id)
            conn.execute(
                """UPDATE tasks SET status='BLOCKED', owner=NULL, lease_until=NULL,
                   next_action=?, updated_at=? WHERE id=?""",
                (
                    "Acknowledge revised decision %s version %d" % (decision_id, version),
                    now,
                    task_id,
                ),
            )
    add_event(
        conn,
        row["mission_id"],
        "decision",
        decision_id,
        "DECISION_REVISED",
        actor,
        {
            "answer": answer,
            "selected_option": selected_option,
            "version": version,
            "affected_tasks": affected,
        },
    )
    reconcile_conn(conn)
    return version


@atomic_write
def link_decision(conn, decision_id, task_id, actor):
    decision = decision_row(conn, decision_id)
    task = task_row(conn, task_id)
    existing = conn.execute(
        "SELECT 1 FROM decision_tasks WHERE decision_id=? AND task_id=?", (decision_id, task_id)
    ).fetchone()
    if existing:
        return False
    if decision["status"] == "CANCELLED":
        raise SwarmError("A withdrawn decision cannot be linked to new work; ask a new question")
    conn.execute(
        "INSERT INTO decision_tasks(decision_id, task_id) VALUES(?,?)", (decision_id, task_id)
    )
    if task["status"] not in TERMINAL_TASK_STATES and task["authorized"]:
        end_attempt(conn, task_id, "INTERRUPTED", "Decision linked: " + decision_id)
        cancel_external_waits(conn, task_id, actor, "Decision linked: " + decision_id)
        conn.execute(
            """UPDATE tasks SET status='BLOCKED', owner=NULL, lease_until=NULL,
               next_action=?, updated_at=? WHERE id=?""",
            ("Consume decision %s" % decision_id, utcnow(), task_id),
        )
    add_event(
        conn,
        decision["mission_id"],
        "decision",
        decision_id,
        "DECISION_LINKED",
        actor,
        {
            "task_id": task_id,
            "decision_version": decision["version"],
            "decision_status": decision["status"],
        },
    )
    reconcile_conn(conn)
    return True


@atomic_write
def acknowledge_decision(conn, decision_id, task_id, agent):
    drow = decision_row(conn, decision_id)
    trow = task_row(conn, task_id)
    require_owner(trow, agent)
    if drow["status"] != "RESOLVED":
        raise SwarmError("Decision %s is not resolved" % decision_id)
    linked = conn.execute(
        "SELECT 1 FROM decision_tasks WHERE decision_id=? AND task_id=?", (decision_id, task_id)
    ).fetchone()
    if not linked:
        raise SwarmError("Decision %s does not affect task %s" % (decision_id, task_id))
    conn.execute(
        """INSERT INTO decision_acks(decision_id, task_id, version, agent_id, acknowledged_at)
           VALUES(?,?,?,?,?) ON CONFLICT(decision_id, task_id) DO UPDATE SET
           version=excluded.version, agent_id=excluded.agent_id, acknowledged_at=excluded.acknowledged_at""",
        (decision_id, task_id, drow["version"], agent, utcnow()),
    )
    add_event(
        conn,
        trow["mission_id"],
        "decision",
        decision_id,
        "DECISION_ACKNOWLEDGED",
        agent,
        {"task_id": task_id, "version": drow["version"]},
    )
