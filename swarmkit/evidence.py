"""Revision-bound evidence contracts and verification results."""

from pathlib import Path

from .core import consistent_read
from .core import (
    ACTIVE_TASK_STATES,
    SwarmError,
    TERMINAL_TASK_STATES,
    atomic_write,
    hash_file,
    json_load,
    make_id,
    utcnow,
)
from .storage import (
    add_event,
    register_artifact,
    require_owner,
    runtime_state,
    task_row,
    unresolved_ack_count,
)


@atomic_write
def set_contract(conn, task_id, revision, environment, actor):
    task = task_row(conn, task_id)
    if task["status"] in TERMINAL_TASK_STATES:
        raise SwarmError("Completed or cancelled task evidence contracts are immutable")
    if not revision.strip() or not environment.strip():
        raise SwarmError("Contract requires exact revision and environment")
    existing = conn.execute("SELECT * FROM task_contracts WHERE task_id=?", (task_id,)).fetchone()
    if task["status"] in ACTIVE_TASK_STATES:
        require_owner(task, actor)
        if unresolved_ack_count(conn, task_id):
            raise SwarmError("Acknowledge current decisions before binding an evidence contract")
        if existing and (existing["revision"], existing["environment"]) != (revision, environment):
            raise SwarmError(
                "An active owner cannot replace a pinned evidence contract; arrange fresh verification"
            )
    if existing and (existing["revision"], existing["environment"]) == (revision, environment):
        return
    conn.execute(
        "INSERT OR REPLACE INTO task_contracts VALUES(?,?,?)", (task_id, revision, environment)
    )
    add_event(
        conn,
        task["mission_id"],
        "task",
        task_id,
        "TASK_CONTRACT_SET",
        actor,
        {"revision": revision, "environment": environment},
    )


@atomic_write
def record_evidence(
    conn,
    task_id,
    agent,
    criterion,
    revision,
    environment,
    command,
    exit_code,
    path,
    idempotency_key=None,
):
    task = task_row(conn, task_id)
    require_owner(task, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError("Acknowledge current decisions before recording evidence")
    if criterion not in json_load(task["acceptance_json"], []):
        raise SwarmError("Evidence criterion must exactly match a task acceptance criterion")
    if not all(x.strip() for x in (revision, environment, command)):
        raise SwarmError("Evidence requires revision, environment, and command")
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SwarmError("Evidence must reference an existing result file")
    mission_revision = runtime_state(conn)["revision"]
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise SwarmError("Evidence idempotency key must not be empty")
        prior = conn.execute(
            "SELECT e.* FROM evidence_record_keys k JOIN evidence e ON e.id=k.evidence_id "
            "WHERE k.task_id=? AND k.key=?",
            (task_id, idempotency_key),
        ).fetchone()
        if prior:
            expected = {
                "generation": task["generation"],
                "mission_revision": mission_revision,
                "acceptance_revision": task["acceptance_revision"],
                "criterion": criterion,
                "revision": revision,
                "environment": environment,
                "command": command,
                "exit_code": exit_code,
                "path": str(path),
            }
            if any(prior[name] != value for name, value in expected.items()):
                raise SwarmError("Evidence key already belongs to a different verification result")
            if hash_file(path)[0] != prior["sha256"]:
                raise SwarmError("Evidence key already belongs to different result file contents")
            return prior["id"]
    evidence_id = make_id("V")
    artifact_id = register_artifact(
        conn, task_id, str(path), kind="verification", note="Evidence " + evidence_id, actor=agent
    )
    # One file observation supplies both records. Rehashing here could bind the
    # evidence and its artifact to different bytes if a result file is replaced.
    sha = conn.execute("SELECT sha256 FROM artifacts WHERE id=?", (artifact_id,)).fetchone()[0]
    if sha is None:
        raise SwarmError("Evidence result file disappeared before registration")
    conn.execute(
        "INSERT INTO evidence(id,task_id,generation,mission_revision,criterion,revision,environment,command,exit_code,path,sha256,created_at,acceptance_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            evidence_id,
            task_id,
            task["generation"],
            mission_revision,
            criterion,
            revision,
            environment,
            command,
            exit_code,
            str(path),
            sha,
            utcnow(),
            task["acceptance_revision"],
        ),
    )
    if idempotency_key is not None:
        conn.execute(
            "INSERT INTO evidence_record_keys VALUES(?,?,?)",
            (task_id, idempotency_key, evidence_id),
        )
    add_event(
        conn,
        task["mission_id"],
        "task",
        task_id,
        "EVIDENCE_RECORDED",
        agent,
        {
            "artifact_id": artifact_id,
            "evidence_id": evidence_id,
            "generation": task["generation"],
            "criterion": criterion,
            "sha256": sha,
            "exit_code": exit_code,
            "idempotency_key": idempotency_key,
        },
    )
    return evidence_id


@consistent_read
def evidence_status(conn, task_id):
    """Explain coverage using the same current result that gates task completion."""
    task = task_row(conn, task_id)
    criteria = json_load(task["acceptance_json"], [])
    contract = conn.execute("SELECT * FROM task_contracts WHERE task_id=?", (task_id,)).fetchone()
    current_revision = runtime_state(conn)["revision"]
    result = {
        "task_id": task_id,
        "generation": task["generation"],
        "mission_revision": current_revision,
        "contract": dict(contract) if contract else None,
        "criteria": [],
        "gaps": [],
    }
    if (
        not isinstance(criteria, list)
        or not criteria
        or not all(isinstance(item, str) and item.strip() for item in criteria)
    ):
        result["gaps"] = ["Task has no valid acceptance criteria"]
        return result
    if not contract:
        result["gaps"] = ["No revision/environment contract"]
        return result
    digests = {}
    for criterion in dict.fromkeys(criteria):
        # The index ends in the rowid internally, so LIMIT selects one result
        # without materializing the task's verification history.
        row = conn.execute(
            "SELECT * FROM evidence WHERE task_id=? AND criterion=? AND generation=? "
            "AND mission_revision=? AND revision=? AND environment=? AND acceptance_revision=? ORDER BY rowid DESC LIMIT 1",
            (
                task_id,
                criterion,
                task["generation"],
                current_revision,
                contract["revision"],
                contract["environment"],
                task["acceptance_revision"],
            ),
        ).fetchone()
        detail = {
            "criterion": criterion,
            "status": "MISSING",
            "reason": "No evidence recorded",
            "evidence": None,
        }
        if row is None:
            latest = conn.execute(
                "SELECT * FROM evidence WHERE task_id=? AND criterion=? ORDER BY rowid DESC LIMIT 1",
                (task_id, criterion),
            ).fetchone()
            if latest:
                differences = [
                    name
                    for name, expected in (
                        ("generation", task["generation"]),
                        ("mission_revision", current_revision),
                        ("acceptance_revision", task["acceptance_revision"]),
                        ("revision", contract["revision"]),
                        ("environment", contract["environment"]),
                    )
                    if latest[name] != expected
                ]
                detail.update(
                    status="STALE",
                    reason="Latest record differs in: " + ", ".join(differences),
                    evidence=dict(latest),
                )
        else:
            detail["evidence"] = dict(row)
            if row["exit_code"] != 0:
                detail.update(
                    status="FAILED", reason="Latest check exited with code %s" % row["exit_code"]
                )
            else:
                if row["path"] not in digests:
                    try:
                        digests[row["path"]] = hash_file(Path(row["path"]))[0]
                    except OSError:
                        digests[row["path"]] = None
                observed = digests[row["path"]]
                if observed is None:
                    detail.update(
                        status="FILE_UNAVAILABLE", reason="Result file is missing or unreadable"
                    )
                elif observed != row["sha256"]:
                    detail.update(
                        status="FILE_CHANGED",
                        reason="Result file no longer matches its recorded hash",
                    )
                else:
                    detail.update(status="PASSED", reason="Current target and result file match")
        result["criteria"].append(detail)
        if detail["status"] != "PASSED":
            result["gaps"].append(criterion)
    result["gaps"].sort()
    return result


@consistent_read
def evidence_gaps(conn, task_id):
    return evidence_status(conn, task_id)["gaps"]


@consistent_read
def evidence_history(conn, task_id, limit=50, before=None):
    """Page through one task's immutable verification records in insertion order."""
    task_row(conn, task_id)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise SwarmError("Evidence limit must be between 1 and 500")
    params = [task_id]
    cursor = ""
    if before:
        row = conn.execute("SELECT rowid,task_id FROM evidence WHERE id=?", (before,)).fetchone()
        if not row or row["task_id"] != task_id:
            raise SwarmError("Evidence cursor must belong to this task")
        cursor = " AND rowid < ?"
        params.append(row["rowid"])
    params.append(limit + 1)
    records = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM evidence WHERE task_id=?" + cursor + " ORDER BY rowid DESC LIMIT ?",
            params,
        )
    ]
    return {
        "records": records[:limit],
        "next_before": records[limit - 1]["id"] if len(records) > limit else None,
    }
