"""Connections, atomic writes, row lookups, and state guards shared by commands."""

from pathlib import Path
import datetime as dt
import sqlite3

from .core import (
    ACTIVE_TASK_STATES,
    SCHEMA_VERSION,
    SwarmError,
    db_path,
    hash_file,
    json_dump,
    json_load,
    make_id,
    parse_time,
    utcnow,
)
from .schema import ensure_schema


def connect(root, require=True):
    path = db_path(root)
    existed = path.exists()
    if require and not path.exists():
        raise SwarmError("No swarm workspace at %s. Run 'init' first." % root)
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    if existed:
        try:
            version_row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            current_version = version_row["value"] if version_row else None
        except sqlite3.OperationalError:
            current_version = None
        if current_version != SCHEMA_VERSION:
            try:
                ensure_schema(conn)
            except Exception:
                conn.close()
                raise
    return conn


def mission(conn):
    row = conn.execute("SELECT * FROM missions ORDER BY created_at LIMIT 1").fetchone()
    if not row:
        raise SwarmError("Mission record is missing")
    return row


def mission_mode(conn):
    row = conn.execute("SELECT value FROM meta WHERE key='mission_mode'").fetchone()
    return row["value"] if row else "FINITE"


def add_event(conn, mission_id, entity_type, entity_id, event_type, actor, payload=None):
    event_id = make_id("E")
    conn.execute(
        "INSERT INTO events(id, mission_id, entity_type, entity_id, event_type, actor, occurred_at, payload_json) VALUES(?,?,?,?,?,?,?,?)",
        (
            event_id,
            mission_id,
            entity_type,
            entity_id,
            event_type,
            actor,
            utcnow(),
            json_dump(payload or {}),
        ),
    )
    return event_id


def task_row(conn, task_id):
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown task: %s" % task_id)
    return row


def decision_row(conn, decision_id):
    row = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown decision: %s" % decision_id)
    return row


def workstream_row(conn, workstream_id):
    row = conn.execute("SELECT * FROM workstreams WHERE id = ?", (workstream_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown workstream: %s" % workstream_id)
    return row


def require_delivery_owner(row, agent):
    if not row:
        raise SwarmError("Unknown delivery")
    if row["status"] != "CLAIMED":
        raise SwarmError("Delivery %s is %s, not CLAIMED" % (row["id"], row["status"]))
    if row["claimed_by"] != agent:
        raise SwarmError(
            "Delivery %s is claimed by %s, not %s" % (row["id"], row["claimed_by"], agent)
        )
    if row["lease_until"] and parse_time(row["lease_until"]) < dt.datetime.now(dt.timezone.utc):
        raise SwarmError("Delivery lease expired; reclaim it before acknowledging")


def all_dependencies_done(conn, task_id):
    row = conn.execute(
        """SELECT COUNT(*) AS remaining FROM task_dependencies d
           JOIN tasks parent ON parent.id = d.depends_on
           WHERE d.task_id = ? AND parent.status <> 'DONE'""",
        (task_id,),
    ).fetchone()
    return row["remaining"] == 0


def open_decision_count(conn, task_id):
    return conn.execute(
        """SELECT COUNT(*) AS n FROM decision_tasks dt
           JOIN decisions d ON d.id = dt.decision_id
           WHERE dt.task_id = ? AND d.status = 'OPEN'""",
        (task_id,),
    ).fetchone()["n"]


def unresolved_ack_count(conn, task_id):
    return conn.execute(
        """SELECT COUNT(*) AS n FROM decision_tasks dt
           JOIN decisions d ON d.id = dt.decision_id
           JOIN tasks t ON t.id = dt.task_id
           LEFT JOIN decision_acks a ON a.decision_id = d.id AND a.task_id = dt.task_id
           WHERE dt.task_id = ? AND d.status = 'RESOLVED'
             AND (a.version IS NULL OR a.version < d.version
                  OR COALESCE(a.agent_id, '') <> COALESCE(t.owner, ''))""",
        (task_id,),
    ).fetchone()["n"]


def finding_row(conn, finding_id):
    row = conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown finding: %s" % finding_id)
    return row


def external_wait_row(conn, wait_id):
    row = conn.execute("SELECT * FROM external_waits WHERE id=?", (wait_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown external wait: %s" % wait_id)
    return row


def require_owner(row, agent):
    if row["status"] not in ACTIVE_TASK_STATES:
        raise SwarmError("Task %s is not active (status %s)" % (row["id"], row["status"]))
    if row["owner"] != agent:
        raise SwarmError("Task %s is owned by %s, not %s" % (row["id"], row["owner"], agent))
    if row["lease_until"] and parse_time(row["lease_until"]) < dt.datetime.now(dt.timezone.utc):
        raise SwarmError("Lease expired for task %s; reclaim it before writing" % row["id"])


def case_row(conn, case_id):
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown case: %s" % case_id)
    return row


def register_artifact(conn, task_id, value, kind="work-product", note=None, actor=None):
    row = task_row(conn, task_id) if task_id else None
    m = mission(conn)
    path = Path(value).expanduser().resolve()
    sha = None
    size = None
    if path.is_file():
        sha, size = hash_file(path)
    artifact_id = make_id("A")
    conn.execute(
        "INSERT INTO artifacts(id, mission_id, task_id, path, kind, sha256, size_bytes, note, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (artifact_id, m["id"], task_id, str(path), kind, sha, size, note, utcnow()),
    )
    event_actor = actor or (row["owner"] if row and row["owner"] else "system")
    add_event(
        conn,
        m["id"],
        "artifact",
        artifact_id,
        "ARTIFACT_REGISTERED",
        event_actor,
        {
            "task_id": task_id,
            "path": str(path),
            "kind": kind,
            "sha256": sha,
            "size_bytes": size,
        },
    )
    return artifact_id


def runtime_state(conn):
    data = dict(conn.execute("SELECT * FROM runtime_state WHERE id=1").fetchone())
    data["limits"] = json_load(data.pop("limits_json"), {})
    return data


def has_unfinished_runs(conn):
    """Unclosed run records require completion or process-lock recovery."""
    return bool(
        conn.execute(
            "SELECT 1 FROM agent_runs WHERE ended_at IS NULL UNION ALL SELECT 1 FROM delivery_runs WHERE ended_at IS NULL LIMIT 1"
        ).fetchone()
    )


def has_active_work(conn):
    return has_unfinished_runs(conn) or bool(
        conn.execute(
            """SELECT 1 FROM tasks WHERE status IN ('CLAIMED','RUNNING','VERIFYING')
           UNION ALL SELECT 1 FROM manager_reviews WHERE status='RUNNING'
           UNION ALL SELECT 1 FROM deliveries WHERE status='CLAIMED'
           UNION ALL SELECT 1 FROM workspace_creations WHERE state='UNKNOWN' LIMIT 1"""
        ).fetchone()
    )


def require_active_mission(conn):
    state = runtime_state(conn)
    if state["desired_state"] != "ACTIVE" or mission(conn)["status"] != "ACTIVE":
        raise SwarmError("Mission is not accepting new work: %s" % state["desired_state"])
    if conn.execute("SELECT 1 FROM manager_reviews WHERE status='ESCALATED'").fetchone():
        raise SwarmError(
            "Manager review retry limit reached; inspect review show and explicitly retry"
        )
    return state


def attempt_for_task(conn, task_id):
    row = task_row(conn, task_id)
    return conn.execute(
        "SELECT * FROM attempts WHERE task_id=? AND generation=?", (task_id, row["generation"])
    ).fetchone()


def end_attempt(conn, task_id, state, reason=None):
    row = task_row(conn, task_id)
    if state in {"CANCELLED", "INTERRUPTED", "EXPIRED", "INCOMPLETE"}:
        conn.execute(
            "UPDATE effects SET state='UNKNOWN',updated_at=? WHERE task_id=? AND generation=? AND state='EXECUTING'",
            (utcnow(), task_id, row["generation"]),
        )
    conn.execute(
        "UPDATE attempts SET state=?, ended_at=?, reason=? WHERE task_id=? AND generation=? AND ended_at IS NULL",
        (state, utcnow(), reason, task_id, row["generation"]),
    )


def cancel_external_waits(conn, task_id, actor, reason):
    """Retire wait subscriptions; never infer that the external job was cancelled."""
    rows = conn.execute(
        "SELECT id,mission_id FROM external_waits WHERE task_id=? AND status='WAITING'",
        (task_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE external_waits SET status='CANCELLED',updated_at=? WHERE id=?",
            (utcnow(), row["id"]),
        )
        add_event(
            conn,
            row["mission_id"],
            "external_wait",
            row["id"],
            "EXTERNAL_WAIT_CANCELLED",
            actor,
            {"task_id": task_id, "reason": reason},
        )
    return [row["id"] for row in rows]


def uncertain_effects(conn, task_id=None):
    sql = "SELECT * FROM effects WHERE state IN ('EXECUTING','UNKNOWN')"
    return conn.execute(
        sql + (" AND task_id=?" if task_id else ""), (task_id,) if task_id else ()
    ).fetchall()


def require_task_capacity(conn, count=1):
    state = runtime_state(conn)
    if state["desired_state"] in {"CANCELLED", "ABANDONED"} or mission(conn)["status"] == "DONE":
        raise SwarmError("Cannot create work in a terminal mission")
    maximum = state["limits"].get("max_tasks")
    if maximum and conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] + count > maximum:
        raise SwarmError("Task quota exhausted")


def budget_reason(conn, task_id=None):
    limits = runtime_state(conn)["limits"]
    if limits.get("deadline") and utcnow() >= limits["deadline"]:
        return "Mission deadline reached"
    if (
        limits.get("max_runs")
        and conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] >= limits["max_runs"]
    ):
        return "Harness run budget exhausted"
    if task_id:
        maximum = limits.get("max_attempts_per_task", 3)
        count = conn.execute(
            "SELECT COUNT(*) FROM attempts WHERE task_id=? AND state IN ('INCOMPLETE','EXPIRED','INTERRUPTED')",
            (task_id,),
        ).fetchone()[0]
        if count >= maximum:
            return "Task attempt budget exhausted (%d)" % maximum
    return None


def stage_task(conn, task_id, actor):
    """New authorizations become visible together when the current review succeeds."""
    require_current_manager(conn, actor)
    review = conn.execute("SELECT id FROM manager_reviews WHERE status='RUNNING'").fetchone()
    if review:
        conn.execute("INSERT OR REPLACE INTO staged_tasks VALUES(?,?)", (task_id, review[0]))
        conn.execute("DELETE FROM review_commits WHERE review_id=?", (review[0],))


def publish_review_tasks(conn, review_id, actor):
    tasks = [
        row[0]
        for row in conn.execute(
            "SELECT task_id FROM staged_tasks WHERE review_id=? ORDER BY task_id", (review_id,)
        )
    ]
    conn.execute("DELETE FROM staged_tasks WHERE review_id=?", (review_id,))
    commitment_ids = [
        r[0] for r in conn.execute("SELECT id FROM commitments WHERE staged_review=?", (review_id,))
    ]
    conn.execute("UPDATE commitments SET staged_review=NULL WHERE staged_review=?", (review_id,))
    add_event(
        conn,
        mission(conn)["id"],
        "manager_review",
        review_id,
        "PLAN_PUBLISHED",
        actor,
        {"task_ids": tasks, "commitment_ids": commitment_ids},
    )


def require_current_manager(conn, actor):
    """Known manager identities cannot mutate a plan after losing their attempt."""
    attempt = conn.execute(
        "SELECT review_id FROM review_attempts WHERE agent=?", (actor,)
    ).fetchone()
    if (
        attempt
        and not conn.execute(
            "SELECT 1 FROM manager_reviews WHERE id=? AND owner=? AND status='RUNNING' AND lease_until>?",
            (attempt[0], actor, utcnow()),
        ).fetchone()
    ):
        raise SwarmError("Manager attempt is no longer current")


def live_process_count(conn):
    """Count durable live or unverified agent and delivery runs under the caller's lock."""
    return conn.execute(
        "SELECT (SELECT COUNT(*) FROM agent_runs WHERE ended_at IS NULL) + "
        "(SELECT COUNT(*) FROM delivery_runs WHERE ended_at IS NULL)"
    ).fetchone()[0]
