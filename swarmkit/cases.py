"""Idempotent service intake, follow-up signals, and case lifecycle."""

from pathlib import Path
import hashlib
import contextlib
import shutil

from .coordination import reconcile_conn
from .core import (
    SwarmError,
    TERMINAL_TASK_STATES,
    atomic_write,
    hash_file,
    json_dump,
    json_load,
    make_id,
    transaction,
    utcnow,
)
from .decisions import resolve_decision
from .delivery import parse_metadata
from .policies import apply_policy, parse_policy_variables
from .queries import case_dict, signal_dict
from .storage import (
    add_event,
    case_row,
    decision_row,
    mission,
    require_task_capacity,
    runtime_state,
    task_row,
)
from .tasks import add_task, cancel_task


@contextlib.contextmanager
def new_payload_files():
    """Remove only snapshots created by a failed intake command."""
    paths = []
    try:
        yield paths
    except BaseException:
        for value in reversed(paths):
            path = Path(value)
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()  # Remove the directory only when it is empty.
            except OSError:
                pass
        raise


def snapshot_case_payload(root, case_id, payload, name, expected=None):
    if not payload:
        return None, None, None
    source = Path(payload).expanduser().resolve()
    if not source.is_file():
        raise SwarmError("Case payload is not a file: %s" % source)
    source_sha, source_size = hash_file(source)
    if expected is not None and expected != (source_sha, source_size):
        raise SwarmError("Case payload changed after the request fingerprint was computed")
    destination_dir = root / "intake" / case_id
    destination_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix if source.suffix else ".txt"
    destination = destination_dir / (name + suffix)
    with new_payload_files() as files:
        files.append(destination)
        shutil.copy2(source, destination)
        copied_sha, copied_size = hash_file(destination)
        if copied_sha != source_sha or copied_size != source_size:
            raise SwarmError("Case payload changed while it was being snapshotted")
    return str(destination), copied_sha, copied_size


@atomic_write
def link_case_task(conn, case_id, task_id, actor):
    case = case_row(conn, case_id)
    if case["status"] == "CANCELLED":
        raise SwarmError("Cancelled cases cannot accept new tasks")
    task = task_row(conn, task_id)
    if case["mission_id"] != task["mission_id"]:
        raise SwarmError("Case and task belong to different missions")
    prior = conn.execute("SELECT case_id FROM case_tasks WHERE task_id=?", (task_id,)).fetchone()
    if prior and prior["case_id"] != case_id:
        raise SwarmError("Task %s already belongs to case %s" % (task_id, prior["case_id"]))
    if prior:
        return False
    task_workstream = conn.execute(
        "SELECT workstream_id FROM task_workstreams WHERE task_id=?", (task_id,)
    ).fetchone()
    if task_workstream and task_workstream["workstream_id"] != case["workstream_id"]:
        raise SwarmError("Task belongs to a different workstream than case %s" % case_id)
    if not task_workstream:
        conn.execute(
            "INSERT INTO task_workstreams(task_id, workstream_id) VALUES(?,?)",
            (task_id, case["workstream_id"]),
        )
    conn.execute(
        "INSERT OR IGNORE INTO case_tasks(case_id, task_id) VALUES(?,?)", (case_id, task_id)
    )
    now = utcnow()
    conn.execute(
        "UPDATE cases SET status='ACTIVE', closed_at=NULL, result_summary=NULL, completion_outcome=NULL, updated_at=? WHERE id=?",
        (now, case_id),
    )
    conn.execute(
        """UPDATE workstreams SET status='ACTIVE', completion_outcome=NULL, progress_summary=NULL, updated_at=?
           WHERE id=? AND status NOT IN ('ACTIVE')""",
        (now, case["workstream_id"]),
    )
    add_event(
        conn,
        case["mission_id"],
        "case",
        case_id,
        "CASE_TASK_LINKED",
        actor,
        {
            "task_id": task_id,
        },
    )
    return not prior


@atomic_write
def open_inquiry(conn, question, actor="human", workstream_id=None, case_id=None, depends_on=None):
    """Create briefing work and reopen its case as one durable operation."""
    question = question.strip()
    if not question:
        raise SwarmError("Inquiry question may not be empty")
    case = case_row(conn, case_id) if case_id else None
    if case:
        if workstream_id and case["workstream_id"] != workstream_id:
            raise SwarmError("Inquiry case and workstream do not match")
        if case["status"] == "CANCELLED":
            raise SwarmError("Cancelled case inquiries must use a separate workstream")
        workstream_id = case["workstream_id"]
        if case["status"] == "DONE":
            conn.execute(
                "UPDATE workstreams SET status='ACTIVE',completion_outcome=NULL,progress_summary=NULL,updated_at=? WHERE id=?",
                (utcnow(), workstream_id),
            )
            add_event(
                conn,
                case["mission_id"],
                "case",
                case_id,
                "CASE_REOPENED_FOR_INQUIRY",
                actor,
                {"question": question},
            )
    task_id = add_task(
        conn,
        "Inquiry: %s" % question.splitlines()[0][:100],
        question,
        "briefing",
        [
            "Answer distinguishes observed facts from inference",
            "Answer cites durable task, event, artifact, or source identifiers",
            "Answer states confidence, uncertainty, and recommended next action",
        ],
        depends_on or [],
        40,
        actor,
        True,
        workstream_id,
    )
    if case:
        link_case_task(conn, case_id, task_id, actor)
    return task_id


def open_case(
    root,
    conn,
    source,
    external_id,
    title,
    objective,
    priority,
    actor,
    acceptance,
    payload=None,
    metadata_items=None,
    policy_id=None,
    policy_variables=None,
    ready=False,
):
    with new_payload_files() as files, transaction(conn):
        values = {
            "source": source.strip(),
            "external_id": external_id.strip(),
            "title": title.strip(),
            "objective": objective.strip(),
        }
        for name, value in values.items():
            if not value:
                raise SwarmError("Case %s may not be empty" % name)
        metadata = parse_metadata(metadata_items or [])
        source_payload = Path(payload).expanduser().resolve() if payload else None
        if source_payload and not source_payload.is_file():
            raise SwarmError("Case payload is not a file: %s" % source_payload)
        payload_sha, payload_size = hash_file(source_payload) if source_payload else (None, None)
        request_fingerprint = hashlib.sha256(
            json_dump(
                {
                    "source": values["source"],
                    "external_id": values["external_id"],
                    "title": values["title"],
                    "objective": values["objective"],
                    "priority": priority,
                    "acceptance": acceptance or [],
                    "payload_sha256": payload_sha,
                    "metadata": metadata,
                    "policy_id": policy_id,
                    "policy_variables": parse_policy_variables(policy_variables or []),
                    "ready": bool(ready),
                }
            ).encode("utf-8")
        ).hexdigest()
        current_mission = mission(conn)
        existing = conn.execute(
            "SELECT * FROM cases WHERE mission_id=? AND source=? AND external_id=?",
            (current_mission["id"], values["source"], values["external_id"]),
        ).fetchone()
        if existing:
            if existing["request_fingerprint"] != request_fingerprint:
                raise SwarmError("Case source/external-id already belongs to a different payload")
            result = case_dict(conn, existing)
            result["created"] = False
            return result
        if current_mission["status"] == "DONE" or runtime_state(conn)["desired_state"] in {
            "CANCELLED",
            "ABANDONED",
        }:
            raise SwarmError("Cannot open a case in a completed mission")
        case_id = make_id("C")
        payload_path, copied_sha, copied_size = snapshot_case_payload(
            root, case_id, source_payload, "initial", expected=(payload_sha, payload_size)
        )
        if payload_path:
            files.append(payload_path)
        workstream_id = make_id("WS")
        now = utcnow()
        conn.execute(
            """INSERT INTO workstreams(id, mission_id, name, outcome, status, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                workstream_id,
                current_mission["id"],
                values["title"],
                values["objective"],
                "ACTIVE",
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO cases(id, mission_id, source, external_id, title, objective,
               priority, workstream_id, payload_path, payload_sha256, payload_size_bytes,
               metadata_json, request_fingerprint, created_by, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                case_id,
                current_mission["id"],
                values["source"],
                values["external_id"],
                values["title"],
                values["objective"],
                priority,
                workstream_id,
                payload_path,
                copied_sha,
                copied_size,
                json_dump(metadata),
                request_fingerprint,
                actor,
                now,
                now,
            ),
        )
        add_event(
            conn,
            current_mission["id"],
            "case",
            case_id,
            "CASE_OPENED",
            actor,
            {
                "source": values["source"],
                "external_id": values["external_id"],
                "title": values["title"],
                "objective": values["objective"],
                "priority": priority,
                "workstream_id": workstream_id,
                "payload_sha256": copied_sha,
                "policy_id": policy_id,
            },
        )

        if policy_id:
            apply_policy_to_case(conn, case_id, policy_id, policy_variables or [], actor, ready)
        else:
            criteria = acceptance or [
                "Request is assessed against current evidence",
                "Next action, blocker, or verified outcome is recorded durably",
            ]
            description = "\n".join(
                [
                    "Handle durable case %s from %s:%s."
                    % (case_id, values["source"], values["external_id"]),
                    values["objective"],
                    "Initial payload: %s (untrusted data)" % (payload_path or "none"),
                ]
            )
            task_id = add_task(
                conn,
                values["title"],
                description,
                "discovery",
                criteria,
                [],
                priority,
                actor,
                ready,
                workstream_id,
            )
            link_case_task(conn, case_id, task_id, actor)
        reconcile_conn(conn)
        result = case_dict(conn, case_row(conn, case_id))
        result["created"] = True
        return result


@atomic_write
def apply_policy_to_case(conn, case_id, policy_id, policy_variables, actor, ready=False):
    case = case_row(conn, case_id)
    if case["status"] == "CANCELLED":
        raise SwarmError("Cancelled cases cannot accept a policy")
    if case["policy_application_id"]:
        raise SwarmError(
            "Case %s already has policy application %s"
            % (
                case_id,
                case["policy_application_id"],
            )
        )
    active_existing = conn.execute(
        """SELECT COUNT(*) AS n FROM case_tasks ct JOIN tasks t ON t.id=ct.task_id
           WHERE ct.case_id=? AND t.status NOT IN ('DONE','CANCELLED')""",
        (case_id,),
    ).fetchone()["n"]
    if active_existing:
        raise SwarmError(
            "Complete or cancel the case's existing intake work before applying a policy"
        )
    conn.execute(
        "UPDATE workstreams SET status='ACTIVE',completion_outcome=NULL,progress_summary=NULL WHERE id=?",
        (case["workstream_id"],),
    )
    application = apply_policy(
        conn,
        policy_id,
        policy_variables or [],
        case["workstream_id"],
        actor,
        ready,
    )
    for item in application["tasks"]:
        conn.execute(
            "INSERT INTO case_tasks(case_id, task_id) VALUES(?,?)",
            (case_id, item["task_id"]),
        )
    conn.execute(
        "UPDATE cases SET policy_application_id=?, status='ACTIVE', completion_outcome=NULL, result_summary=NULL, closed_at=NULL, updated_at=? WHERE id=?",
        (application["id"], utcnow(), case_id),
    )
    add_event(
        conn,
        case["mission_id"],
        "case",
        case_id,
        "CASE_POLICY_APPLIED",
        actor,
        {
            "policy_application_id": application["id"],
            "policy_id": policy_id,
            "tasks": [item["task_id"] for item in application["tasks"]],
        },
    )
    reconcile_conn(conn)
    return case_dict(conn, case_row(conn, case_id))


@atomic_write
def wake_case_from_signal(conn, case_id, signal_id, actor, ready=True):
    case = case_row(conn, case_id)
    signal = conn.execute("SELECT * FROM case_signals WHERE id=?", (signal_id,)).fetchone()
    if not signal or signal["case_id"] != case_id:
        raise SwarmError("Signal does not belong to case %s" % case_id)
    existing = conn.execute(
        "SELECT task_id FROM case_signal_tasks WHERE signal_id=?", (signal_id,)
    ).fetchone()
    if existing:
        return existing["task_id"]
    if case["status"] == "CANCELLED":
        raise SwarmError("Cancelled cases cannot be woken")
    now = utcnow()
    require_task_capacity(conn)
    task_id = make_id("T")
    conn.execute(
        """UPDATE workstreams SET status='ACTIVE', completion_outcome=NULL, progress_summary=NULL, updated_at=? WHERE id=?""",
        (now, case["workstream_id"]),
    )
    conn.execute(
        """INSERT INTO tasks(id, mission_id, title, description, kind, priority,
           authorized, acceptance_json, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id,
            case["mission_id"],
            "Assess follow-up: %s" % case["title"],
            "Assess durable signal %s for case %s and record the justified next action."
            % (signal_id, case_id),
            "discovery",
            case["priority"],
            1 if ready else 0,
            json_dump(
                [
                    "Signal is assessed against current case evidence",
                    "Response, blocker, or next action is recorded durably",
                ]
            ),
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO task_workstreams(task_id, workstream_id) VALUES(?,?)",
        (
            task_id,
            case["workstream_id"],
        ),
    )
    conn.execute("INSERT INTO case_tasks(case_id, task_id) VALUES(?,?)", (case_id, task_id))
    conn.execute(
        "INSERT INTO case_signal_tasks(signal_id,task_id) VALUES(?,?)", (signal_id, task_id)
    )
    conn.execute(
        "UPDATE cases SET status='ACTIVE', closed_at=NULL, result_summary=NULL, completion_outcome=NULL, updated_at=? WHERE id=?",
        (now, case_id),
    )
    add_event(
        conn,
        case["mission_id"],
        "task",
        task_id,
        "TASK_PROPOSED",
        actor,
        {
            "title": "Assess follow-up: %s" % case["title"],
            "kind": "discovery",
            "authorized": bool(ready),
            "case_id": case_id,
            "signal_id": signal_id,
            "workstream_id": case["workstream_id"],
        },
    )
    add_event(
        conn,
        case["mission_id"],
        "case",
        case_id,
        "CASE_WOKEN",
        actor,
        {
            "signal_id": signal_id,
            "task_id": task_id,
        },
    )
    reconcile_conn(conn)
    return task_id


def add_case_signal(
    root,
    conn,
    case_id,
    source,
    external_id,
    kind,
    author,
    body,
    actor,
    payload=None,
    metadata_items=None,
    decision_id=None,
    wake=False,
):
    with new_payload_files() as files, transaction(conn):
        case = case_row(conn, case_id)
        source = source.strip()
        external_id = external_id.strip()
        kind = kind.strip()
        body = body.strip()
        if not source or not external_id or not kind or not body:
            raise SwarmError("Signal source, external-id, kind, and body are required")
        if decision_id and wake:
            raise SwarmError("Use either --decision or --wake for one signal, not both")
        if decision_id:
            decision = decision_row(conn, decision_id)
            linked = conn.execute(
                """SELECT 1 FROM decision_tasks dt JOIN case_tasks ct ON ct.task_id=dt.task_id
                   WHERE dt.decision_id=? AND ct.case_id=?""",
                (decision_id, case_id),
            ).fetchone()
            if not linked:
                raise SwarmError("Decision %s is not linked to case %s" % (decision_id, case_id))
            # Late replies remain evidence even after their question was withdrawn.
            if decision["status"] not in {"OPEN", "RESOLVED", "CANCELLED"}:
                raise SwarmError("Decision %s cannot be resolved" % decision_id)
        metadata = parse_metadata(metadata_items or [])
        source_payload = Path(payload).expanduser().resolve() if payload else None
        if source_payload and not source_payload.is_file():
            raise SwarmError("Signal payload is not a file: %s" % source_payload)
        payload_sha, payload_size = hash_file(source_payload) if source_payload else (None, None)
        existing = conn.execute(
            "SELECT * FROM case_signals WHERE mission_id=? AND source=? AND external_id=?",
            (case["mission_id"], source, external_id),
        ).fetchone()
        if existing:
            same = (
                existing["case_id"] == case_id
                and existing["kind"] == kind
                and (existing["author"] or "") == (author or "")
                and existing["body"] == body
                and existing["payload_sha256"] == payload_sha
                and json_load(existing["metadata_json"], {}) == metadata
                and existing["resolves_decision_id"] == decision_id
            )
            if not same:
                raise SwarmError("Signal source/external-id already belongs to a different payload")
            if decision_id and decision_row(conn, decision_id)["status"] == "OPEN":
                resolve_decision(conn, decision_id, body, actor)
            wake_task_id = None
            if wake:
                wake_task_id = wake_case_from_signal(
                    conn, case_id, existing["id"], actor, ready=True
                )
            result = signal_dict(existing)
            result["created"] = False
            result["wake_task_id"] = wake_task_id
            return result
        signal_id = make_id("S")
        payload_path, copied_sha, copied_size = snapshot_case_payload(
            root,
            case_id,
            source_payload,
            "signal-%s" % signal_id,
            expected=(payload_sha, payload_size),
        )
        if payload_path:
            files.append(payload_path)
        now = utcnow()
        conn.execute(
            """INSERT INTO case_signals(id, mission_id, case_id, source, external_id,
               kind, author, body, payload_path, payload_sha256, payload_size_bytes,
               metadata_json, resolves_decision_id, recorded_by, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                signal_id,
                case["mission_id"],
                case_id,
                source,
                external_id,
                kind,
                author,
                body,
                payload_path,
                copied_sha,
                copied_size,
                json_dump(metadata),
                decision_id,
                actor,
                now,
            ),
        )
        add_event(
            conn,
            case["mission_id"],
            "signal",
            signal_id,
            "CASE_SIGNAL_RECORDED",
            actor,
            {
                "case_id": case_id,
                "source": source,
                "external_id": external_id,
                "kind": kind,
                "author": author,
                "payload_sha256": copied_sha,
                "resolves_decision_id": decision_id,
            },
        )
        add_event(
            conn,
            case["mission_id"],
            "case",
            case_id,
            "CASE_UPDATED_BY_SIGNAL",
            actor,
            {
                "signal_id": signal_id,
                "kind": kind,
                "resolves_decision_id": decision_id,
            },
        )
        if decision_id and decision_row(conn, decision_id)["status"] == "OPEN":
            resolve_decision(conn, decision_id, body, actor)
        wake_task_id = None
        if wake:
            wake_task_id = wake_case_from_signal(conn, case_id, signal_id, actor, ready=True)
        reconcile_conn(conn)
        result = signal_dict(
            conn.execute("SELECT * FROM case_signals WHERE id=?", (signal_id,)).fetchone()
        )
        result["created"] = True
        result["wake_task_id"] = wake_task_id
        return result


@atomic_write
def cancel_case(conn, case_id, actor, reason):
    case = case_row(conn, case_id)
    if not reason.strip():
        raise SwarmError("Case cancellation requires a reason")
    if case["status"] == "CANCELLED":
        raise SwarmError("Case %s is already cancelled" % case_id)
    now = utcnow()
    linked = [
        row[0] for row in conn.execute("SELECT task_id FROM case_tasks WHERE case_id=?", (case_id,))
    ]
    conn.execute(
        """UPDATE cases SET status='CANCELLED',completion_outcome='CANCELLED',
            result_summary=?,updated_at=?,closed_at=? WHERE id=?""",
        (reason, now, now, case_id),
    )
    conn.execute(
        """UPDATE workstreams SET status='CANCELLED',completion_outcome='CANCELLED',
            progress_summary=?,updated_at=? WHERE id=?""",
        (reason, now, case["workstream_id"]),
    )
    cancelled = []
    for task_id in linked:
        if task_row(conn, task_id)["status"] not in TERMINAL_TASK_STATES:
            cancel_task(conn, task_id, actor, reason)
            cancelled.append(task_id)
    add_event(
        conn,
        case["mission_id"],
        "case",
        case_id,
        "CASE_CANCELLED",
        actor,
        {"reason": reason, "cancelled_tasks": cancelled},
    )
    reconcile_conn(conn)
