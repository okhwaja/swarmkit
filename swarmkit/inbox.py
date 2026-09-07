"""Read, lease, and acknowledge durable event deliveries."""

from .core import SwarmError, atomic_write, future_time, json_dump, json_load, make_id, utcnow
from .storage import mission, task_row


def inbox(conn, agent, after=None, advance=False, task_id=None):
    cursor = conn.execute(
        "SELECT last_event_seq FROM cursors WHERE agent_id=?", (agent,)
    ).fetchone()
    start = after if after is not None else (cursor["last_event_seq"] if cursor else 0)
    if task_id:
        task_row(conn, task_id)
        task_ids = [task_id] + [
            r["depends_on"]
            for r in conn.execute(
                "SELECT depends_on FROM task_dependencies WHERE task_id=?", (task_id,)
            )
        ]
        placeholders = ",".join("?" for _ in task_ids)
        decision_ids = [
            r["decision_id"]
            for r in conn.execute(
                "SELECT decision_id FROM decision_tasks WHERE task_id IN (%s)" % placeholders,
                task_ids,
            )
        ]
        artifact_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE task_id IN (%s)" % placeholders, task_ids
            )
        ]
        fact_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM facts WHERE task_id IN (%s)" % placeholders, task_ids
            )
        ]
        run_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM agent_runs WHERE task_id IN (%s)" % placeholders, task_ids
            )
        ]
        finding_ids = [
            r["id"]
            for r in conn.execute(
                """SELECT DISTINCT f.id FROM findings f LEFT JOIN finding_tasks ft ON ft.finding_id=f.id
               WHERE f.source_task_id IN (%s) OR ft.task_id IN (%s)"""
                % (placeholders, placeholders),
                task_ids + task_ids,
            )
        ]
        wait_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM external_waits WHERE task_id IN (%s)" % placeholders, task_ids
            )
        ]
        wait_signal_ids = []
        if wait_ids:
            wait_placeholders = ",".join("?" for _ in wait_ids)
            wait_signal_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM wait_signals WHERE wait_id IN (%s)" % wait_placeholders,
                    wait_ids,
                )
            ]
        case_ids = [
            r["case_id"]
            for r in conn.execute(
                "SELECT case_id FROM case_tasks WHERE task_id IN (%s)" % placeholders, task_ids
            )
        ]
        signal_ids = []
        if case_ids:
            case_placeholders = ",".join("?" for _ in case_ids)
            signal_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM case_signals WHERE case_id IN (%s)" % case_placeholders,
                    case_ids,
                )
            ]
        entity_ids = (
            task_ids
            + decision_ids
            + artifact_ids
            + fact_ids
            + run_ids
            + case_ids
            + signal_ids
            + finding_ids
            + wait_ids
            + wait_signal_ids
            + [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM effects WHERE task_id IN (%s)" % placeholders, task_ids
                )
            ]
        )
        entity_placeholders = ",".join("?" for _ in entity_ids)
        m = mission(conn)
        rows = conn.execute(
            "SELECT * FROM events WHERE seq > ? AND (entity_id=? OR entity_id IN (%s)) ORDER BY seq"
            % entity_placeholders,
            [start, m["id"]] + entity_ids,
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq", (start,)).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["payload"] = json_load(data.pop("payload_json"), {})
        result.append(data)
    if advance and rows:
        last = rows[-1]["seq"]
        conn.execute(
            """INSERT INTO cursors(agent_id, last_event_seq, updated_at) VALUES(?,?,?)
               ON CONFLICT(agent_id) DO UPDATE SET last_event_seq=excluded.last_event_seq, updated_at=excluded.updated_at""",
            (agent, last, utcnow()),
        )
        conn.commit()
    return result


@atomic_write
def lease_inbox(conn, agent, task_id=None, limit=50, lease_seconds=300):
    if not 1 <= limit <= 500:
        raise SwarmError("Inbox batch limit must be between 1 and 500")
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
        offset = conn.execute(
            "SELECT last_seq FROM inbox_offsets WHERE agent=? AND scope=?", (agent, scope)
        ).fetchone()
        start = offset[0] if offset else 0
        events = inbox(conn, agent, after=start, task_id=task_id)[:limit]
    if not events:
        return {"token": None, "events": []}
    token, lease = make_id("I"), future_time(lease_seconds)
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
    conn.execute(
        "INSERT INTO inbox_offsets VALUES(?,?,?) ON CONFLICT(agent,scope) DO UPDATE SET last_seq=MAX(last_seq,excluded.last_seq)",
        (agent, row["scope"], row["end_seq"]),
    )
    conn.execute("UPDATE inbox_deliveries SET acked_at=? WHERE token=?", (utcnow(), token))
    return {"acknowledged": True, "duplicate": False}
