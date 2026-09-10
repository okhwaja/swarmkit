"""One decision-attention projection and durable, scoped transitions."""

from .core import consistent_read, parse_time, utcnow
from .storage import add_event, mission, runtime_state

HUMAN_KINDS = {"human_decision", "missing_access", "safety_stop"}


@consistent_read
def decision_attention(conn, at=None):
    now = at or utcnow()
    decisions = {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT id,kind,question,created_at FROM decisions WHERE status='OPEN' ORDER BY created_at,id"
        )
    }
    for item in decisions.values():
        item.update(
            age_seconds=max(
                0, int((parse_time(now) - parse_time(item["created_at"])).total_seconds())
            ),
            task_ids=[],
            case_ids=[],
            requires_human=item["kind"] in HUMAN_KINDS,
            next_action="decision show " + item["id"],
        )
    if not decisions:
        return []
    for row in conn.execute(
        "SELECT dt.decision_id,t.id,ct.case_id FROM decision_tasks dt "
        "JOIN decisions d ON d.id=dt.decision_id JOIN tasks t ON t.id=dt.task_id "
        "LEFT JOIN case_tasks ct ON ct.task_id=t.id "
        "WHERE d.status='OPEN' AND t.status NOT IN ('DONE','CANCELLED') ORDER BY t.id"
    ):
        item = decisions[row[0]]
        item["task_ids"].append(row[1])
        if row[2] and row[2] not in item["case_ids"]:
            item["case_ids"].append(row[2])
    return list(decisions.values())


def reconcile_attention(conn, actor, now):
    """Called inside reconciliation's write transaction, never by a read projection."""
    items = decision_attention(conn, now)
    human = [item for item in items if item["requires_human"]]
    desired = {("decision", item["id"]): [item] for item in human}
    for item in human:
        for case_id in item["case_ids"]:
            desired.setdefault(("case", case_id), []).append(item)
    previous = {
        (row["scope"], row["entity_id"]): row
        for row in conn.execute("SELECT * FROM attention_transitions WHERE active=1")
    }
    if not human and not previous:
        return
    runnable = conn.execute(
        "SELECT 1 FROM tasks t WHERE (status IN ('CLAIMED','RUNNING','VERIFYING') OR "
        "(status='READY' AND NOT EXISTS (SELECT 1 FROM staged_tasks s WHERE s.task_id=t.id))) LIMIT 1"
    ).fetchone()
    current_mission = mission(conn)
    if (
        human
        and any(item["task_ids"] for item in human)
        and not runnable
        and runtime_state(conn)["desired_state"] == "ACTIVE"
    ):
        desired[("mission", current_mission["id"])] = human
    for key in sorted(set(desired) | {key for key, row in previous.items() if row["active"]}):
        active = key in desired
        old = previous.get(key)
        if old is None:
            old = conn.execute(
                "SELECT * FROM attention_transitions WHERE scope=? AND entity_id=?", key
            ).fetchone()
        if old and bool(old["active"]) == active:
            continue
        version = old["version"] + 1 if old else 1
        conn.execute(
            "INSERT INTO attention_transitions VALUES(?,?,?,?,?) ON CONFLICT(scope,entity_id) "
            "DO UPDATE SET active=excluded.active,version=excluded.version,since=excluded.since",
            (key[0], key[1], int(active), version, now),
        )
        event = (
            {
                "decision": "DECISION_NEEDS_ATTENTION",
                "case": "CASE_BLOCKED_ON_HUMAN",
                "mission": "MISSION_BLOCKED_ON_HUMAN",
            }[key[0]]
            if active
            else "HUMAN_BLOCK_CLEARED"
        )
        add_event(
            conn,
            current_mission["id"],
            key[0],
            key[1],
            event,
            actor,
            {
                "scope": key[0],
                "transition_version": version,
                "blocked_since": now if active else None,
                "decisions": desired.get(key, []),
            },
        )
    threshold = runtime_state(conn)["limits"].get("decision_escalation_seconds")
    if threshold:
        for item in human:
            if item["age_seconds"] >= threshold:
                changed = conn.execute(
                    "INSERT OR IGNORE INTO decision_aging VALUES(?,?)", (item["id"], threshold)
                )
                if changed.rowcount:
                    add_event(
                        conn,
                        current_mission["id"],
                        "decision",
                        item["id"],
                        "DECISION_AGING",
                        actor,
                        {"threshold_seconds": threshold, "decision": item},
                    )
