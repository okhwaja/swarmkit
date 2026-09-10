"""Scoped conditional grants. Trusted harnesses supply checks and enforce authority."""

from pathlib import Path

from .core import (
    SwarmError,
    atomic_write,
    consistent_read,
    canonical_time,
    hash_file,
    json_dump,
    json_load,
    make_id,
    parse_time,
    utcnow,
)
from .storage import (
    add_event,
    decision_row,
    mission,
    require_owner,
    runtime_state,
    task_row,
    register_artifact,
    unresolved_ack_count,
)


def validate_grant(specification):
    fields = {
        "provider",
        "action",
        "resources",
        "revision",
        "environment",
        "delegate",
        "expires_at",
        "conditions",
    }
    if not isinstance(specification, dict) or set(specification) != fields:
        raise SwarmError(
            "Grant requires provider, action, resources, revision, environment, delegate, expires_at and conditions"
        )
    for name in ("provider", "action", "revision", "environment", "delegate"):
        if not isinstance(specification[name], str) or not specification[name].strip():
            raise SwarmError("Grant %s must be a nonempty string" % name)
    resources = specification["resources"]
    if (
        not isinstance(resources, list)
        or not resources
        or not all(isinstance(x, str) and x.strip() and x != "*" for x in resources)
    ):
        raise SwarmError("Grant resources must be an explicit nonempty allowlist")
    if canonical_time(specification["expires_at"]) <= utcnow():
        raise SwarmError("Grant must expire in the future")
    conditions = specification["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise SwarmError("Grant requires at least one named condition")
    seen = set()
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {
            "id",
            "check",
            "waivable",
            "max_age_seconds",
        }:
            raise SwarmError("Each condition requires id, check, waivable and max_age_seconds")
        if not all(
            isinstance(condition[key], str) and condition[key].strip() for key in ("id", "check")
        ):
            raise SwarmError("Condition id and trusted check name must be nonempty strings")
        if condition["id"] in seen:
            raise SwarmError("Condition ids must be unique")
        seen.add(condition["id"])
        if not isinstance(condition["waivable"], bool):
            raise SwarmError("Condition waivable must be boolean")
        age = condition["max_age_seconds"]
        if not isinstance(age, int) or isinstance(age, bool) or age < 1:
            raise SwarmError("Condition max_age_seconds must be a positive integer")
    return specification


@atomic_write
def issue_grant(conn, decision_id, choice, specification, actor):
    from .decisions import require_decision_choice

    require_decision_choice(conn, decision_id, choice)
    specification = validate_grant(specification)
    decision = decision_row(conn, decision_id)
    grant_id = make_id("G")
    conn.execute(
        "INSERT INTO grants VALUES(?,?,?,?,?,?,NULL,NULL)",
        (grant_id, decision_id, decision["version"], json_dump(specification), actor, utcnow()),
    )
    add_event(
        conn,
        decision["mission_id"],
        "grant",
        grant_id,
        "GRANT_ISSUED",
        actor,
        {
            "decision_id": decision_id,
            "decision_version": decision["version"],
            "specification": specification,
        },
    )
    return grant_id


def current_grant(conn, grant_id):
    row = conn.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown grant: " + grant_id)
    spec = json_load(row["specification_json"], {})
    decision = decision_row(conn, row["decision_id"])
    if row["revoked_at"] or canonical_time(spec["expires_at"]) <= utcnow():
        raise SwarmError("Grant is revoked or expired")
    if decision["status"] != "RESOLVED" or decision["version"] != row["decision_version"]:
        raise SwarmError("Grant belongs to an obsolete decision version")
    return row, spec


@atomic_write
def revoke_grant(conn, grant_id, actor, reason):
    row = conn.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
    if not row or not reason.strip():
        raise SwarmError("Grant revocation requires an existing grant and reason")
    if actor != row["issued_by"]:
        raise SwarmError("Only the recorded issuer may revoke this grant")
    if row["revoked_at"]:
        return False
    conn.execute(
        "UPDATE grants SET revoked_at=?,revocation_reason=? WHERE id=?",
        (utcnow(), reason, grant_id),
    )
    add_event(
        conn, mission(conn)["id"], "grant", grant_id, "GRANT_REVOKED", actor, {"reason": reason}
    )
    return True


@atomic_write
def waive_condition(conn, grant_id, condition_id, actor, reason, expires_at):
    row, spec = current_grant(conn, grant_id)
    condition = next((item for item in spec["conditions"] if item["id"] == condition_id), None)
    if not condition or not condition["waivable"]:
        raise SwarmError("Condition is absent or non-waivable")
    if actor not in {row["issued_by"], spec["delegate"]} or not reason.strip():
        raise SwarmError("Waiver requires its issuer or named delegate and a reason")
    expiry = canonical_time(expires_at)
    if not utcnow() < expiry <= canonical_time(spec["expires_at"]):
        raise SwarmError("Waiver expiry must be in the future and within the grant lifetime")
    waiver_id = make_id("GW")
    conn.execute(
        "INSERT INTO grant_waivers VALUES(?,?,?,?,?,?,?)",
        (waiver_id, grant_id, condition_id, actor, reason, expiry, utcnow()),
    )
    add_event(
        conn,
        mission(conn)["id"],
        "grant",
        grant_id,
        "GRANT_CONDITION_WAIVED",
        actor,
        {
            "waiver_id": waiver_id,
            "condition_id": condition_id,
            "reason": reason,
            "expires_at": expiry,
        },
    )
    return waiver_id


@atomic_write
def record_condition(
    conn,
    grant_id,
    task_id,
    agent,
    condition_id,
    check,
    revision,
    environment,
    exit_code,
    path,
    observed_at,
    expires_at,
):
    _, spec = current_grant(conn, grant_id)
    task = task_row(conn, task_id)
    require_owner(task, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError("Acknowledge current decisions before recording grant checks")
    condition = next((item for item in spec["conditions"] if item["id"] == condition_id), None)
    if not condition or check != condition["check"]:
        raise SwarmError("Result does not match the grant's trusted check name")
    if (revision, environment) != (spec["revision"], spec["environment"]):
        raise SwarmError("Result revision or environment does not match the grant")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise SwarmError("Exit code must be an integer")
    observed, expires = canonical_time(observed_at), canonical_time(expires_at)
    now = utcnow()
    if (
        observed > now
        or expires <= now
        or expires <= observed
        or (parse_time(expires) - parse_time(observed)).total_seconds()
        > condition["max_age_seconds"]
    ):
        raise SwarmError("Result must be current, with a bounded observation lifetime")
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SwarmError("Grant check must reference an existing result file")
    artifact_id = register_artifact(
        conn, task_id, str(path), kind="grant_check", note="Grant " + grant_id, actor=agent
    )
    sha = conn.execute("SELECT sha256 FROM artifacts WHERE id=?", (artifact_id,)).fetchone()[0]
    if sha is None:
        raise SwarmError("Grant result disappeared during recording")
    require_owner(task, agent)
    current_grant(conn, grant_id)
    if expires <= utcnow():
        raise SwarmError("Grant result expired during recording")
    identifier = make_id("GE")
    conn.execute(
        "INSERT INTO grant_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            grant_id,
            task_id,
            task["generation"],
            runtime_state(conn)["revision"],
            task["acceptance_revision"],
            condition_id,
            revision,
            environment,
            exit_code,
            str(path),
            sha,
            observed,
            expires,
            agent,
        ),
    )
    add_event(
        conn,
        task["mission_id"],
        "grant",
        grant_id,
        "GRANT_CONDITION_RECORDED",
        agent,
        {
            "evaluation_id": identifier,
            "task_id": task_id,
            "condition_id": condition_id,
            "exit_code": exit_code,
        },
    )
    return identifier


@consistent_read
def require_grant(
    conn, grant_id, task_id, agent, provider, action, resource, revision, environment
):
    """Recheck immediately in the transaction that records an effect's start."""
    _, spec = current_grant(conn, grant_id)
    task = task_row(conn, task_id)
    require_owner(task, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError("Acknowledge current decisions before using a grant")
    if (provider, action, revision, environment) != (
        spec["provider"],
        spec["action"],
        spec["revision"],
        spec["environment"],
    ) or resource not in spec["resources"]:
        raise SwarmError("Action is outside the grant's exact scope")
    now = utcnow()
    results = []
    for condition in spec["conditions"]:
        result = conn.execute(
            "SELECT * FROM grant_evaluations WHERE grant_id=? AND task_id=? AND condition_id=? "
            "ORDER BY rowid DESC LIMIT 1",
            (grant_id, task_id, condition["id"]),
        ).fetchone()
        valid = bool(
            result
            and result["exit_code"] == 0
            and result["expires_at"] > now
            and (
                result["generation"],
                result["mission_revision"],
                result["acceptance_revision"],
                result["revision"],
                result["environment"],
            )
            == (
                task["generation"],
                runtime_state(conn)["revision"],
                task["acceptance_revision"],
                revision,
                environment,
            )
        )
        if valid:
            try:
                valid = hash_file(Path(result["path"]))[0] == result["sha256"]
            except OSError:
                valid = False
        waiver = (
            conn.execute(
                "SELECT id,expires_at FROM grant_waivers WHERE grant_id=? AND condition_id=? AND expires_at>? ORDER BY rowid DESC LIMIT 1",
                (grant_id, condition["id"], now),
            ).fetchone()
            if condition["waivable"]
            else None
        )
        results.append(
            {
                "condition_id": condition["id"],
                "passed": valid,
                "result_expires_at": result["expires_at"] if valid else None,
                "waiver_id": waiver[0] if waiver else None,
                "waiver_expires_at": waiver[1] if waiver else None,
            }
        )
    # Hashing result files may cross either the grant expiry or the worker lease.
    current_grant(conn, grant_id)
    require_owner(task, agent)
    checked_at = utcnow()
    for item in results:
        if item["passed"] and item["result_expires_at"] <= checked_at:
            item["passed"] = False
        if item["waiver_id"] and item["waiver_expires_at"] <= checked_at:
            item["waiver_id"] = None
    if any(not item["passed"] and not item["waiver_id"] for item in results):
        raise SwarmError("Grant conditions are not satisfied: " + json_dump(results))
    return results
