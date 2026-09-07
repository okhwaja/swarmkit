"""Read, lease, and acknowledge durable event deliveries."""

import contextlib

from .core import (
    SwarmError,
    atomic_write,
    future_time,
    json_dump,
    json_load,
    make_id,
    transaction,
    utcnow,
)
from .storage import task_row


# Keep scope expansion inside SQLite: a long-lived case can have more related
# entities than SQLite allows bound parameters, even when reading a tiny page.
TASK_SCOPE = """
WITH target_tasks(id) AS (
    SELECT ? UNION SELECT depends_on FROM task_dependencies WHERE task_id=?
), target_cases(id) AS (
    SELECT case_id FROM case_tasks WHERE task_id IN target_tasks
), target_waits(id) AS (
    SELECT id FROM external_waits WHERE task_id IN target_tasks
), target_entities(id) AS (
    SELECT id FROM missions
    UNION SELECT id FROM target_tasks
    UNION SELECT decision_id FROM decision_tasks WHERE task_id IN target_tasks
    UNION SELECT id FROM artifacts WHERE task_id IN target_tasks
    UNION SELECT id FROM facts WHERE task_id IN target_tasks
    UNION SELECT id FROM agent_runs WHERE task_id IN target_tasks
    UNION SELECT id FROM findings WHERE source_task_id IN target_tasks
    UNION SELECT finding_id FROM finding_tasks WHERE task_id IN target_tasks
    UNION SELECT id FROM target_waits
    UNION SELECT id FROM wait_signals WHERE wait_id IN target_waits
    UNION SELECT id FROM target_cases
    UNION SELECT id FROM case_signals WHERE case_id IN target_cases
    UNION SELECT id FROM effects WHERE task_id IN target_tasks
)
"""


def inbox_offset(conn, agent, scope):
    row = conn.execute(
        "SELECT last_seq FROM inbox_offsets WHERE agent=? AND scope=?", (agent, scope)
    ).fetchone()
    if row:
        return row[0]
    # Before scoped offsets existed, the legacy cursor covered the whole mission.
    # Never apply that cursor to a different task's independent delivery stream.
    if scope == "*":
        row = conn.execute(
            "SELECT last_event_seq FROM cursors WHERE agent_id=?", (agent,)
        ).fetchone()
        if row:
            return row[0]
    return 0


def validate_page(limit):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise SwarmError("Inbox batch limit must be between 1 and 500")


def advance_offset(conn, agent, scope, sequence):
    conn.execute(
        """INSERT INTO inbox_offsets VALUES(?,?,?)
           ON CONFLICT(agent,scope) DO UPDATE SET last_seq=MAX(last_seq,excluded.last_seq)""",
        (agent, scope, sequence),
    )


def inbox(conn, agent, after=None, advance=False, task_id=None, limit=50):
    """Read one ordered page. Reading alone never consumes events.

    Use the last returned sequence as ``after`` to inspect the next page, or use
    lease/ack for crash-safe consumption. Each task scope has its own offset.
    """
    validate_page(limit)
    if after is not None and (not isinstance(after, int) or after < 0):
        raise SwarmError("Inbox --after must be a non-negative event sequence")
    with transaction(conn) if advance else contextlib.nullcontext():
        scope = task_id or "*"
        start = after if after is not None else inbox_offset(conn, agent, scope)
        if task_id:
            task_row(conn, task_id)
            rows = conn.execute(
                TASK_SCOPE
                + """SELECT * FROM events
                    WHERE seq > ? AND entity_id IN target_entities ORDER BY seq LIMIT ?""",
                (task_id, task_id, start, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (start, limit)
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["payload"] = json_load(data.pop("payload_json"), {})
            result.append(data)
        if advance and rows:
            advance_offset(conn, agent, scope, rows[-1]["seq"])
        return result


@atomic_write
def lease_inbox(conn, agent, task_id=None, limit=50, lease_seconds=300):
    validate_page(limit)
    lease = future_time(lease_seconds)
    scope = task_id or "*"
    existing = conn.execute(
        "SELECT * FROM inbox_deliveries WHERE agent=? AND scope=? AND acked_at IS NULL",
        (agent, scope),
    ).fetchone()
    if existing and existing["lease_until"] > utcnow():
        return {
            "token": existing["token"],
            "lease_until": existing["lease_until"],
            "events": json_load(existing["payload_json"]),
        }
    if existing:
        events = json_load(existing["payload_json"])
        start = existing["start_seq"]
        conn.execute("DELETE FROM inbox_deliveries WHERE token=?", (existing["token"],))
    else:
        start = inbox_offset(conn, agent, scope)
        events = inbox(conn, agent, after=start, task_id=task_id, limit=limit)
    if not events:
        return {"token": None, "events": []}
    token = make_id("I")
    conn.execute(
        "INSERT INTO inbox_deliveries VALUES(?,?,?,?,?,?,?,NULL)",
        (token, agent, scope, start, events[-1]["seq"], json_dump(events), lease),
    )
    return {"token": token, "lease_until": lease, "events": events}


@atomic_write
def ack_inbox(conn, token, agent):
    row = conn.execute(
        "SELECT * FROM inbox_deliveries WHERE token=? AND agent=?", (token, agent)
    ).fetchone()
    if not row:
        raise SwarmError("Unknown inbox token or wrong recipient")
    if row["acked_at"]:
        return {"acknowledged": True, "duplicate": True}
    if row["lease_until"] <= utcnow():
        raise SwarmError("Inbox lease expired; obtain a new delivery before acknowledging")
    advance_offset(conn, agent, row["scope"], row["end_seq"])
    conn.execute("UPDATE inbox_deliveries SET acked_at=? WHERE token=?", (utcnow(), token))
    return {"acknowledged": True, "duplicate": False}
