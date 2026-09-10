"""Track external actions and lease shared resources without blind retries."""

from .core import SwarmError, atomic_write, future_time, json_dump, make_id, utcnow
from .storage import (
    add_event,
    mission,
    require_active_mission,
    require_owner,
    task_row,
    uncertain_effects,
    unresolved_ack_count,
)


@atomic_write
def prepare_effect(
    conn,
    task_id,
    agent,
    key,
    target,
    revision,
    parameters,
    grant_id=None,
    provider=None,
    action=None,
    environment=None,
):
    require_active_mission(conn)
    task = task_row(conn, task_id)
    require_owner(task, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError("Acknowledge current decisions before preparing effects")
    if not all(str(x).strip() for x in (key, target, revision)):
        raise SwarmError("Effects require an idempotency key, target, and exact revision")
    grant_scope = (grant_id, provider, action, target, environment)
    if any(value is not None for value in (grant_id, provider, action, environment)):
        if not all((grant_id, provider, action, environment)):
            raise SwarmError("Grant-backed effects require grant, provider, action and environment")
        from .grants import require_grant

        require_grant(
            conn, grant_id, task_id, agent, provider, action, target, revision, environment
        )
    encoded = json_dump(parameters)
    existing = conn.execute("SELECT * FROM effects WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        binding = conn.execute(
            "SELECT grant_id,provider,action,resource,environment FROM effect_grants WHERE effect_id=?",
            (existing["id"],),
        ).fetchone()
        if (tuple(binding) if binding else None) != (grant_scope if grant_id else None):
            raise SwarmError("Effect retry cannot change or remove its grant binding")
        if (
            existing["task_id"],
            existing["target"],
            existing["revision"],
            existing["parameters_json"],
        ) != (task_id, target, revision, encoded):
            raise SwarmError("Idempotency key reused with different action parameters")
        if existing["state"] == "NOT_APPLIED" or (
            existing["state"] == "PREPARED" and existing["generation"] != task["generation"]
        ):
            conn.execute(
                "UPDATE effects SET generation=?,state='PREPARED',receipt=NULL,updated_at=? WHERE id=?",
                (task["generation"], utcnow(), existing["id"]),
            )
            add_event(
                conn,
                task["mission_id"],
                "effect",
                existing["id"],
                (
                    "EFFECT_ADOPTED"
                    if existing["generation"] != task["generation"]
                    else "EFFECT_REPREPARED"
                ),
                agent,
                {
                    "task_id": task_id,
                    "generation": task["generation"],
                    "previous_state": existing["state"],
                },
            )
            existing = conn.execute(
                "SELECT * FROM effects WHERE id=?", (existing["id"],)
            ).fetchone()
        return dict(existing)
    effect_id = make_id("E")
    conn.execute(
        "INSERT INTO effects VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            effect_id,
            task_id,
            task["generation"],
            key,
            target,
            revision,
            encoded,
            "PREPARED",
            None,
            utcnow(),
            utcnow(),
        ),
    )
    if grant_id:
        conn.execute("INSERT INTO effect_grants VALUES(?,?,?,?,?,?)", (effect_id,) + grant_scope)
    add_event(
        conn,
        task["mission_id"],
        "effect",
        effect_id,
        "EFFECT_PREPARED",
        agent,
        {
            "task_id": task_id,
            "generation": task["generation"],
            "target": target,
            "revision": revision,
            "idempotency_key": key,
        },
    )
    return dict(conn.execute("SELECT * FROM effects WHERE id=?", (effect_id,)).fetchone())


@atomic_write
def transition_effect(conn, effect_id, action, actor, receipt=None):
    row = conn.execute("SELECT * FROM effects WHERE id=?", (effect_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown effect")
    if action == "start":
        require_active_mission(conn)
        task = task_row(conn, row["task_id"])
        require_owner(task, actor)
        if unresolved_ack_count(conn, task["id"]):
            raise SwarmError("Acknowledge current decisions before starting an effect")
        if task["generation"] != row["generation"] or row["state"] != "PREPARED":
            raise SwarmError("Effect is stale or already started; reconcile rather than retry")
        binding = conn.execute(
            "SELECT * FROM effect_grants WHERE effect_id=?", (effect_id,)
        ).fetchone()
        if binding:
            from .grants import require_grant

            results = require_grant(
                conn,
                binding["grant_id"],
                task["id"],
                actor,
                binding["provider"],
                binding["action"],
                binding["resource"],
                row["revision"],
                binding["environment"],
            )
            add_event(
                conn,
                task["mission_id"],
                "effect",
                effect_id,
                "EFFECT_GRANT_CHECKED",
                actor,
                {"grant_id": binding["grant_id"], "conditions": results},
            )
        state = "EXECUTING"
    else:
        if action not in {"succeeded", "failed", "unknown", "not-applied"}:
            raise SwarmError("Unknown effect transition")
        if not receipt or not receipt.strip():
            raise SwarmError("Reconciliation requires a provider receipt or observation")
        state = {
            "succeeded": "SUCCEEDED",
            "failed": "FAILED",
            "unknown": "UNKNOWN",
            "not-applied": "NOT_APPLIED",
        }[action]
        if row["state"] == state and row["receipt"] == receipt:
            return dict(row)
        if row["state"] not in {"EXECUTING", "UNKNOWN"}:
            raise SwarmError("Only executing or uncertain effects can be reconciled")
    conn.execute(
        "UPDATE effects SET state=?,receipt=?,updated_at=? WHERE id=?",
        (state, receipt, utcnow(), effect_id),
    )
    add_event(
        conn,
        mission(conn)["id"],
        "effect",
        effect_id,
        "EFFECT_" + state,
        actor,
        {"task_id": row["task_id"], "generation": row["generation"], "receipt": receipt},
    )
    return dict(conn.execute("SELECT * FROM effects WHERE id=?", (effect_id,)).fetchone())


@atomic_write
def acquire_resource(conn, resource, task_id, agent, lease_seconds=300):
    require_active_mission(conn)
    task = task_row(conn, task_id)
    require_owner(task, agent)
    existing = conn.execute(
        "SELECT * FROM resource_leases WHERE resource=?", (resource,)
    ).fetchone()
    if existing:
        live_run = conn.execute(
            "SELECT 1 FROM agent_runs WHERE task_id=? AND ended_at IS NULL", (existing["task_id"],)
        ).fetchone()
        same = existing["task_id"] == task_id and existing["generation"] == task["generation"]
        if not same and (
            existing["lease_until"] > utcnow()
            or live_run
            or uncertain_effects(conn, existing["task_id"])
        ):
            raise SwarmError("Resource is held by another attempt: %s" % resource)
    token = existing["token"] if existing and same else make_id("L")
    lease = min(future_time(lease_seconds), task["lease_until"])
    conn.execute(
        "INSERT OR REPLACE INTO resource_leases VALUES(?,?,?,?,?)",
        (resource, task_id, task["generation"], token, lease),
    )
    add_event(
        conn,
        task["mission_id"],
        "task",
        task_id,
        "RESOURCE_ACQUIRED",
        agent,
        {
            "resource": resource,
            "generation": task["generation"],
            "token": token,
            "lease_until": lease,
        },
    )
    return {"token": token, "lease_until": lease}


@atomic_write
def release_resource(conn, token, agent):
    row = conn.execute("SELECT * FROM resource_leases WHERE token=?", (token,)).fetchone()
    if not row:
        raise SwarmError("Unknown resource token")
    attempt = conn.execute(
        "SELECT * FROM attempts WHERE task_id=? AND generation=?",
        (row["task_id"], row["generation"]),
    ).fetchone()
    if not attempt or attempt["agent"] != agent:
        raise SwarmError("Resource token belongs to another attempt")
    if uncertain_effects(conn, row["task_id"]):
        raise SwarmError("Reconcile uncertain effects before releasing the resource")
    conn.execute("DELETE FROM resource_leases WHERE token=?", (token,))
    add_event(
        conn,
        mission(conn)["id"],
        "task",
        row["task_id"],
        "RESOURCE_RELEASED",
        agent,
        {"resource": row["resource"]},
    )
