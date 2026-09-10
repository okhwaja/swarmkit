"""Delivery obligations that survive task boundaries. Providers remain harness-owned."""

from .core import (
    SwarmError,
    atomic_write,
    consistent_read,
    json_dump,
    json_load,
    make_id,
    utcnow,
    canonical_time,
    parse_time,
)
from .storage import (
    add_event,
    mission,
    task_row,
    require_owner,
    require_current_manager,
    runtime_state,
    uncertain_effects,
    unresolved_ack_count,
)


def row_for(conn, identifier):
    row = conn.execute("SELECT * FROM commitments WHERE id=?", (identifier,)).fetchone()
    if not row:
        raise SwarmError("Unknown commitment: " + identifier)
    return row


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise SwarmError("Commitment requires nonempty " + name)
    return value


def schedule(next_check, deadline, signal_expected):
    deadline = canonical_time(deadline)
    next_check = canonical_time(next_check) if next_check else None
    now = utcnow()
    if deadline <= now or (next_check and not now < next_check <= deadline):
        raise SwarmError("Commitment schedule must be future and no later than its deadline")
    if not isinstance(signal_expected, bool) or not (signal_expected or next_check):
        raise SwarmError("Commitment requires next check or expected signal")
    return next_check, deadline


def record(conn, row, key, kind, payload, actor):
    nonempty(key, "idempotency key")
    previous = conn.execute(
        "SELECT * FROM commitment_records WHERE commitment_id=? AND key=?", (row["id"], key)
    ).fetchone()
    if previous:
        if previous["kind"] != kind or json_load(previous["payload_json"]) != payload:
            raise SwarmError("Commitment key belongs to different input")
        return False
    conn.execute(
        "INSERT INTO commitment_records VALUES(?,?,?,?,?,?,?)",
        (make_id("CR"), row["id"], key, kind, json_dump(payload), actor, utcnow()),
    )
    add_event(conn, row["mission_id"], "commitment", row["id"], kind, actor, payload)
    return True


def replay(conn, row, key, kind, payload):
    previous = conn.execute(
        "SELECT kind,payload_json FROM commitment_records WHERE commitment_id=? AND key=?",
        (row["id"], key),
    ).fetchone()
    if not previous:
        return False
    if previous[0] != kind or json_load(previous[1]) != payload:
        raise SwarmError("Commitment key belongs to different input")
    return True


def require_open(conn, row, version):
    if row["status"] != "OPEN" or row["version"] != version:
        raise SwarmError("Commitment is terminal or its version changed; retrieve commitment show")
    if row["staged_review"]:
        raise SwarmError("Commitment awaits plan publication")
    if row["mission_revision"] != runtime_state(conn)["revision"]:
        raise SwarmError("Commitment requires explicit adoption after mission amendment")


def worker(conn, row, task_id, agent, producer=False):
    if task_id not in (
        {row["producer_task"], row["followup_task"]} if producer else {row["followup_task"]}
    ):
        raise SwarmError("Task is not assigned to this commitment")
    task = task_row(conn, task_id)
    require_owner(task, agent)
    if unresolved_ack_count(conn, task_id):
        raise SwarmError("Acknowledge current decisions before commitment writes")
    return task


def scopes(conn, producer, followup):
    p, f = task_row(conn, producer), task_row(conn, followup)
    if producer == followup or p["mission_id"] != f["mission_id"]:
        raise SwarmError("Commitment needs distinct producer and follow-up tasks in one mission")
    streams = []
    cases = []
    for task in (producer, followup):
        streams.append(
            {
                r[0]
                for r in conn.execute(
                    "SELECT workstream_id FROM task_workstreams WHERE task_id=?", (task,)
                )
            }
        )
        cases.append(
            {r[0] for r in conn.execute("SELECT case_id FROM case_tasks WHERE task_id=?", (task,))}
        )
    if streams[0] != streams[1] or cases[0] != cases[1]:
        raise SwarmError("Producer and follow-up must have the same workstream and case scope")
    if (
        conn.execute(
            "SELECT 1 FROM workstreams WHERE id IN (SELECT workstream_id FROM task_workstreams WHERE task_id=?) AND status='CANCELLED'",
            (producer,),
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM cases WHERE id IN (SELECT case_id FROM case_tasks WHERE task_id=?) AND status='CANCELLED'",
            (producer,),
        ).fetchone()
    ):
        raise SwarmError("Cannot enroll a cancelled scope")
    if f["status"] in {"DONE", "CANCELLED"}:
        raise SwarmError("Follow-up task must be nonterminal")
    return next(iter(streams[0]), None)


@atomic_write
def create_commitment(conn, specification, actor, key):
    require_current_manager(conn, actor)
    nonempty(key, "creation key")
    required = {
        "producer_task",
        "followup_task",
        "title",
        "provider",
        "environment",
        "terminal_check",
        "responsible",
        "next_check_at",
        "deadline_at",
        "signal_expected",
    }
    if not isinstance(specification, dict) or set(specification) != required:
        raise SwarmError("Commitment specification requires: " + ", ".join(sorted(required)))
    previous = conn.execute("SELECT * FROM commitments WHERE creation_key=?", (key,)).fetchone()
    if previous:
        if json_load(previous["specification_json"]) != specification:
            raise SwarmError("Commitment creation key belongs to different work")
        return commitment_dict(conn, previous)
    if mission(conn)["status"] == "DONE" or runtime_state(conn)["desired_state"] not in {
        "ACTIVE",
        "PAUSED",
    }:
        raise SwarmError("Cannot create commitment in terminal or draining mission")
    for name in required - {"next_check_at", "deadline_at", "signal_expected"}:
        nonempty(specification[name], name)
    stream = scopes(conn, specification["producer_task"], specification["followup_task"])
    for task_id in (specification["producer_task"], specification["followup_task"]):
        if (
            task_row(conn, task_id)["owner"]
            or conn.execute(
                "SELECT 1 FROM agent_runs WHERE task_id=? AND ended_at IS NULL", (task_id,)
            ).fetchone()
        ):
            raise SwarmError(
                "Create delivery scope before dispatch or after both tasks are quiescent"
            )
    if task_row(conn, specification["producer_task"])["status"] == "CANCELLED":
        raise SwarmError("Cannot create commitment for cancelled production")
    if conn.execute(
        "SELECT 1 FROM commitments WHERE followup_task=? AND status='OPEN'",
        (specification["followup_task"],),
    ).fetchone():
        raise SwarmError("Follow-up already owns an open commitment")
    next_check, deadline = schedule(
        specification["next_check_at"],
        specification["deadline_at"],
        specification["signal_expected"],
    )
    review = conn.execute("SELECT id FROM manager_reviews WHERE status='RUNNING'").fetchone()
    identifier, now = make_id("CM"), utcnow()
    conn.execute(
        """INSERT INTO commitments(id,mission_id,producer_task,followup_task,workstream_id,
        title,provider,environment,terminal_check,responsible,mission_revision,next_check_at,deadline_at,
        signal_expected,staged_review,created_at,updated_at,creation_key,specification_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            identifier,
            mission(conn)["id"],
            specification["producer_task"],
            specification["followup_task"],
            stream,
            specification["title"],
            specification["provider"],
            specification["environment"],
            specification["terminal_check"],
            specification["responsible"],
            runtime_state(conn)["revision"],
            next_check,
            deadline,
            int(specification["signal_expected"]),
            review[0] if review else None,
            now,
            now,
            key,
            json_dump(specification),
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO required_handoffs VALUES(?)", (specification["producer_task"],)
    )
    if review:
        conn.execute("DELETE FROM review_commits WHERE review_id=?", (review[0],))
    row = row_for(conn, identifier)
    # Explicit enrollment can reopen completed task-derived scopes, never cancellations.
    if stream:
        conn.execute(
            "UPDATE workstreams SET status='ACTIVE',completion_outcome=NULL WHERE id=? AND status='DONE'",
            (stream,),
        )
    conn.execute(
        "UPDATE cases SET status='WAITING_EXTERNAL',completion_outcome=NULL,closed_at=NULL,result_summary=NULL WHERE status='DONE' AND id IN (SELECT case_id FROM case_tasks WHERE task_id=?)",
        (specification["producer_task"],),
    )
    record(conn, row, "created", "COMMITMENT_CREATED", specification, actor)
    return commitment_dict(conn, row)


@atomic_write
def bind_commitment(conn, identifier, task_id, agent, version, external_ref, revision, key):
    row = row_for(conn, identifier)
    worker(conn, row, task_id, agent, producer=True)
    nonempty(external_ref, "external_ref")
    nonempty(revision, "revision")
    payload = {
        "task_id": task_id,
        "version": version,
        "external_ref": external_ref,
        "revision": revision,
    }
    if replay(conn, row, key, "COMMITMENT_BOUND", payload):
        return commitment_dict(conn, row)
    require_open(conn, row, version)
    if row["external_ref"] and row["external_ref"] != external_ref:
        raise SwarmError("Cannot replace the provider object; create a new commitment")
    if uncertain_effects(conn, task_id):
        raise SwarmError("Reconcile uncertain effects before changing commitment scope")
    record(conn, row, key, "COMMITMENT_BOUND", payload, agent)
    conn.execute(
        "UPDATE commitments SET external_ref=?,revision=?,version=version+1,updated_at=? WHERE id=?",
        (external_ref, revision, utcnow(), identifier),
    )
    return commitment_dict(conn, row_for(conn, identifier))


@atomic_write
def observe_commitment(conn, identifier, task_id, agent, version, observation, key):
    row = row_for(conn, identifier)
    task = worker(conn, row, task_id, agent)
    fields = {
        "provider",
        "external_ref",
        "revision",
        "environment",
        "check",
        "observed_at",
        "outcome",
        "receipt",
    }
    if not isinstance(observation, dict) or set(observation) != fields:
        raise SwarmError("Observation requires: " + ", ".join(sorted(fields)))
    for name in fields:
        nonempty(observation[name], name)
    if observation["outcome"] not in {"pending", "satisfied", "rejected", "unknown"}:
        raise SwarmError("Observation outcome must be pending, satisfied, rejected or unknown")
    payload = {
        "version": version,
        "task_id": task_id,
        "observation": observation,
        "generation": task["generation"],
        "acceptance_revision": task["acceptance_revision"],
        "mission_revision": row["mission_revision"],
    }
    if replay(conn, row, key, "COMMITMENT_OBSERVED", payload):
        return commitment_dict(conn, row)
    require_open(conn, row, version)
    for field, column in (
        ("provider", "provider"),
        ("external_ref", "external_ref"),
        ("revision", "revision"),
        ("environment", "environment"),
        ("check", "terminal_check"),
    ):
        if observation[field] != row[column]:
            raise SwarmError("Observation does not match commitment " + field)
    observed = canonical_time(observation["observed_at"])
    age = (parse_time(utcnow()) - parse_time(observed)).total_seconds()
    if not 0 <= age <= 300:
        raise SwarmError("Provider observation must be current (at most 300 seconds old)")
    if observation["outcome"] == "satisfied" and uncertain_effects(conn, task_id):
        raise SwarmError("Reconcile uncertain effects before recording delivery success")
    if (
        observation["outcome"] == "satisfied"
        and task_row(conn, row["producer_task"])["status"] != "DONE"
    ):
        raise SwarmError("Complete production before satisfying its delivery")
    # Replay fingerprint includes task provenance, preventing adoption of older attempts.
    record(conn, row, key, "COMMITMENT_OBSERVED", payload, agent)
    if observation["outcome"] == "satisfied":
        conn.execute(
            "UPDATE commitments SET status='SATISFIED',result=?,next_check_at=NULL,updated_at=? WHERE id=?",
            (observation["receipt"], utcnow(), identifier),
        )
    else:
        from .coordination import request_manager_review

        if observation["outcome"] == "rejected":
            request_manager_review(
                conn, "delivery requires replanning", "commitment", identifier, "URGENT"
            )
    return commitment_dict(conn, row_for(conn, identifier))


@atomic_write
def wait_commitment(
    conn, identifier, task_id, agent, version, next_check, deadline, signal_expected, key
):
    row = row_for(conn, identifier)
    worker(conn, row, task_id, agent)
    payload = dict(
        version=version,
        task_id=task_id,
        next_check_at=next_check,
        deadline_at=deadline,
        signal_expected=signal_expected,
    )
    if replay(conn, row, key, "COMMITMENT_WAITING", payload):
        return commitment_dict(conn, row)
    require_open(conn, row, version)
    if not row["external_ref"]:
        raise SwarmError("Bind provider object before waiting")
    signal = (
        conn.execute(
            "SELECT MAX(rowid) FROM commitment_records WHERE commitment_id=? AND kind='COMMITMENT_SIGNAL'",
            (identifier,),
        ).fetchone()[0]
        or 0
    )
    observation = (
        conn.execute(
            "SELECT MAX(rowid) FROM commitment_records WHERE commitment_id=? AND kind='COMMITMENT_OBSERVED'",
            (identifier,),
        ).fetchone()[0]
        or 0
    )
    if signal > observation:
        raise SwarmError(
            "Inspect provider and record an observation after the latest signal before waiting"
        )
    # Use the existing wait primitive to retire the attempt and release its slot.
    from .coordination import start_external_wait

    start_external_wait(
        conn,
        task_id,
        agent,
        row["terminal_check"],
        row["external_ref"],
        deadline,
        next_check,
        signal_expected,
    )
    record(conn, row, key, "COMMITMENT_WAITING", payload, agent)
    conn.execute(
        "UPDATE commitments SET next_check_at=?,deadline_at=?,signal_expected=?,version=version+1,updated_at=? WHERE id=?",
        (
            *schedule(next_check, deadline, signal_expected),
            int(signal_expected),
            utcnow(),
            identifier,
        ),
    )
    return commitment_dict(conn, row_for(conn, identifier))


@atomic_write
def signal_commitment(conn, identifier, source, external_id, external_ref, note, actor):
    row = row_for(conn, identifier)
    for name, value in (
        ("source", source),
        ("external_id", external_id),
        ("external_ref", external_ref),
    ):
        nonempty(value, name)
    if source != row["provider"] or external_ref != row["external_ref"]:
        raise SwarmError("Signal provider/object does not match commitment")
    payload = dict(source=source, external_id=external_id, external_ref=external_ref, note=note)
    key = "signal:" + json_dump([source, external_id])
    if record(conn, row, key, "COMMITMENT_SIGNAL", payload, actor) and row["status"] == "OPEN":
        wake(conn, row, "EXTERNAL_SIGNAL", key, actor)
    return commitment_dict(conn, row_for(conn, identifier))


def wake(conn, row, reason, key, actor):
    if row["staged_review"] or row["mission_revision"] != runtime_state(conn)["revision"]:
        return
    if not record(
        conn,
        row,
        "wake:" + key,
        "COMMITMENT_CHECK_DUE",
        {"reason": reason, "version": row["version"]},
        actor,
    ):
        return
    from .coordination import request_manager_review, _wake_external_wait

    for wait in conn.execute(
        "SELECT * FROM external_waits WHERE task_id=? AND status='WAITING'", (row["followup_task"],)
    ).fetchall():
        _wake_external_wait(
            conn,
            wait,
            (
                reason
                if reason in {"DEADLINE", "SCHEDULED_CHECK", "EXTERNAL_SIGNAL"}
                else "SCHEDULED_CHECK"
            ),
            "commitment",
            None,
            actor,
            "Verify commitment " + row["id"],
        )
    request_manager_review(
        conn,
        "delivery " + reason.lower(),
        "commitment",
        row["id"],
        "URGENT" if reason in {"DEADLINE", "TRACKING_GAP"} else "NORMAL",
    )
    conn.execute("UPDATE commitments SET next_check_at=NULL WHERE id=?", (row["id"],))


@atomic_write
def reconcile_commitments(conn, actor="reconciler", at=None):
    now = at or utcnow()
    rows = conn.execute(
        "SELECT * FROM commitments WHERE status='OPEN' AND staged_review IS NULL"
    ).fetchall()
    if not rows:
        return
    revision = runtime_state(conn)["revision"]
    from .coordination import request_manager_review

    for row in rows:
        if row["mission_revision"] != revision:
            if record(
                conn,
                row,
                "amend:" + str(revision),
                "COMMITMENT_ADOPTION_REQUIRED",
                {"mission_revision": revision},
                actor,
            ):
                request_manager_review(
                    conn, "delivery adoption required", "commitment", row["id"], "URGENT"
                )
            continue
        signals = conn.execute(
            "SELECT key FROM commitment_records s WHERE commitment_id=? AND kind='COMMITMENT_SIGNAL' AND NOT EXISTS (SELECT 1 FROM commitment_records w WHERE w.commitment_id=s.commitment_id AND w.key='wake:' || s.key) ORDER BY rowid DESC LIMIT 1",
            (row["id"],),
        ).fetchall()
        for signal in signals:
            wake(conn, row, "EXTERNAL_SIGNAL", signal[0], actor)
        if task_row(conn, row["followup_task"])["status"] in {"DONE", "CANCELLED"}:
            wake(conn, row, "TRACKING_GAP", "gap:" + str(row["version"]), actor)
        if row["deadline_at"] <= now:
            wake(conn, row, "DEADLINE", "deadline:" + str(row["version"]), actor)
        elif row["next_check_at"] and row["next_check_at"] <= now:
            wake(conn, row, "SCHEDULED_CHECK", "schedule:" + str(row["version"]), actor)


@atomic_write
def adopt_commitment(conn, identifier, followup_task, actor, version, reason, key):
    row = row_for(conn, identifier)
    require_current_manager(conn, actor)
    nonempty(reason, "adoption reason")
    payload = dict(version=version, followup_task=followup_task, reason=reason)
    if replay(conn, row, key, "COMMITMENT_ADOPTED", payload):
        return commitment_dict(conn, row)
    if row["status"] != "OPEN" or row["version"] != version:
        raise SwarmError("Commitment is terminal or version changed")
    if runtime_state(conn)["desired_state"] not in {"ACTIVE", "PAUSED"}:
        raise SwarmError("Cannot adopt in terminal/draining mission")
    for task_id in {row["followup_task"], followup_task}:
        task = task_row(conn, task_id)
        if (
            task["owner"]
            or conn.execute(
                "SELECT 1 FROM agent_runs WHERE task_id=? AND ended_at IS NULL", (task_id,)
            ).fetchone()
            or uncertain_effects(conn, task_id)
        ):
            raise SwarmError("Adoption requires quiescent tasks and reconciled effects")
    scopes(conn, row["producer_task"], followup_task)
    from .storage import cancel_external_waits

    cancel_external_waits(conn, row["followup_task"], actor, "Delivery responsibility reassigned")
    if task_row(conn, row["followup_task"])["status"] == "WAITING_EXTERNAL":
        conn.execute("UPDATE tasks SET status='PROPOSED' WHERE id=?", (row["followup_task"],))
    review = conn.execute("SELECT id FROM manager_reviews WHERE status='RUNNING'").fetchone()
    record(conn, row, key, "COMMITMENT_ADOPTED", payload, actor)
    conn.execute(
        "UPDATE commitments SET followup_task=?,mission_revision=?,version=version+1,staged_review=?,updated_at=? WHERE id=?",
        (
            followup_task,
            runtime_state(conn)["revision"],
            review[0] if review else None,
            utcnow(),
            identifier,
        ),
    )
    if review:
        conn.execute("DELETE FROM review_commits WHERE review_id=?", (review[0],))
    return commitment_dict(conn, row_for(conn, identifier))


@atomic_write
def cancel_commitment(conn, identifier, actor, version, reason):
    row = row_for(conn, identifier)
    require_current_manager(conn, actor)
    nonempty(reason, "cancellation reason")
    if row["status"] != "OPEN" or row["version"] != version:
        raise SwarmError("Commitment is terminal or version changed")
    record(conn, row, "cancel:" + str(version), "COMMITMENT_CANCELLED", {"reason": reason}, actor)
    conn.execute(
        "UPDATE commitments SET status='CANCELLED',version=version+1,result=?,next_check_at=NULL,updated_at=? WHERE id=?",
        (reason, utcnow(), identifier),
    )
    return commitment_dict(conn, row_for(conn, identifier))


def require_handoff(conn, task_id):
    if not conn.execute("SELECT 1 FROM required_handoffs WHERE task_id=?", (task_id,)).fetchone():
        return
    rows = conn.execute(
        "SELECT * FROM commitments WHERE producer_task=? AND status!='CANCELLED'", (task_id,)
    ).fetchall()
    if not rows or any(
        not r["external_ref"]
        or not r["revision"]
        or r["staged_review"]
        or r["mission_revision"] != runtime_state(conn)["revision"]
        or task_row(conn, r["followup_task"])["status"] in {"DONE", "CANCELLED"}
        for r in rows
    ):
        raise SwarmError(
            "Production requires a bound, published delivery commitment and nonterminal follow-up"
        )


@consistent_read
def commitment_dict(conn, row):
    data = dict(row)
    data["specification"] = json_load(data.pop("specification_json"))
    data["tracking_gap"] = row["status"] == "OPEN" and task_row(conn, row["followup_task"])[
        "status"
    ] in {"DONE", "CANCELLED"}
    data["adoption_required"] = (
        row["status"] == "OPEN" and row["mission_revision"] != runtime_state(conn)["revision"]
    )
    data["retrieve"] = "commitment show " + row["id"]
    return data


@consistent_read
def list_commitments(conn, task_id=None):
    query, args = "SELECT * FROM commitments", ()
    if task_id:
        query += " WHERE producer_task=? OR followup_task=?"
        args = (task_id, task_id)
    return [commitment_dict(conn, row) for row in conn.execute(query + " ORDER BY rowid", args)]


def render_commitments(items):
    lines = ["## Delivery commitments", ""]
    if not items:
        return lines + ["None recorded.", ""]
    for item in items:
        lines += [
            "- `%s` **%s** — %s; responsible: %s; follow-up: `%s`; next check: %s; deadline: %s%s%s"
            % (
                item["id"],
                item["status"],
                item["title"],
                item["responsible"],
                item["followup_task"],
                item["next_check_at"] or "signal/manager review",
                item["deadline_at"],
                "; TRACKING GAP" if item["tracking_gap"] else "",
                "; ADOPTION REQUIRED" if item["adoption_required"] else "",
            )
        ]
    return lines + [""]
