"""Revision-bound evidence contracts and verification results."""

from pathlib import Path

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
    conn, task_id, agent, criterion, revision, environment, command, exit_code, path
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
    sha, _ = hash_file(path)
    evidence_id = make_id("V")
    conn.execute(
        "INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            evidence_id,
            task_id,
            task["generation"],
            runtime_state(conn)["revision"],
            criterion,
            revision,
            environment,
            command,
            exit_code,
            str(path),
            sha,
            utcnow(),
        ),
    )
    artifact_id = register_artifact(
        conn, task_id, str(path), kind="verification", note="Evidence " + evidence_id, actor=agent
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
        },
    )
    return evidence_id


def evidence_gaps(conn, task_id):
    task = task_row(conn, task_id)
    criteria = json_load(task["acceptance_json"], [])
    if (
        not isinstance(criteria, list)
        or not criteria
        or not all(isinstance(item, str) and item.strip() for item in criteria)
    ):
        return ["Task has no valid acceptance criteria"]
    contract = conn.execute("SELECT * FROM task_contracts WHERE task_id=?", (task_id,)).fetchone()
    if not contract:
        return ["No revision/environment contract"]
    covered = set()
    for row in conn.execute(
        "SELECT * FROM evidence WHERE task_id=? AND generation=? AND mission_revision=? AND exit_code=0",
        (task_id, task["generation"], runtime_state(conn)["revision"]),
    ):
        path = Path(row["path"])
        if (
            row["revision"] == contract["revision"]
            and row["environment"] == contract["environment"]
            and path.is_file()
            and hash_file(path)[0] == row["sha256"]
        ):
            covered.add(row["criterion"])
    return sorted(set(criteria) - covered)
