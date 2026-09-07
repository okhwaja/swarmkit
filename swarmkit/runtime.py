"""Launch harness processes, recover interrupted runs, and schedule ready work."""

from pathlib import Path
import concurrent.futures
import time

from .config import render_command, runner_config
from .coordination import (
    claim_manager_review,
    finish_manager_review,
    reconcile_conn,
    request_manager_review,
)
from .core import (
    ACTIVE_TASK_STATES,
    SwarmError,
    atomic_write,
    hash_file,
    json_dump,
    make_id,
    process_lock,
    run_logged_process,
    utcnow,
)
from .delivery import abandon_delivery_run
from .prompts import role_for_task, write_prompt
from .queries import external_wait_dict
from .storage import (
    add_event,
    attempt_for_task,
    budget_reason,
    connect,
    end_attempt,
    mission,
    require_active_mission,
    require_owner,
    runtime_state,
    task_row,
    uncertain_effects,
)
from .tasks import claim_task


def task_working_directory(conn, task_id, default):
    if not task_id:
        return default
    pending = conn.execute(
        "SELECT id FROM workspace_creations WHERE task_id=? AND state IN ('UNKNOWN','CREATED')",
        (task_id,),
    ).fetchone()
    if pending:
        raise SwarmError(
            "Checkout creation requires reconciliation or attachment before dispatch: "
            + pending["id"]
        )
    workspace = conn.execute("SELECT path FROM workspaces WHERE task_id=?", (task_id,)).fetchone()
    if workspace:
        path = Path(workspace["path"])
        if not path.is_dir():
            raise SwarmError("Registered workspace is missing; restore it before dispatch")
        return path
    return default


def dispatch(root, role, agent, task_id=None, dry_run=False):
    config = runner_config(root)
    prompt_path = write_prompt(root, role, agent, task_id)
    model = config.get("models", {}).get(role, "")
    workdir = Path(config.get("working_directory") or root.parent).expanduser().resolve()
    conn = connect(root)
    try:
        if task_id:
            workdir = task_working_directory(conn, task_id, workdir)
            attempt = attempt_for_task(conn, task_id)
            if attempt and attempt["generation"] > 1:
                model = config.get("escalation_models", {}).get(role, model)
    finally:
        conn.close()
    values = {
        "prompt_file": str(prompt_path),
        "role": role,
        "task_id": task_id or "",
        "agent_id": agent,
        "root": str(root),
        "workdir": str(workdir),
        "model": model,
    }
    if dry_run:
        command = render_command(config["command"], values, "Runner command")
        return {"command": command, "prompt_path": str(prompt_path), "model": model}
    run_id = make_id("R")
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with process_lock(run_dir / "process.lock") as run_lock:
        conn = connect(root)
        try:
            conn.execute("BEGIN IMMEDIATE")
            require_active_mission(conn)
            # Re-read checkout authorization under the same write lock as the run
            # record. Registration/recovery may have changed since prompt creation.
            workdir = task_working_directory(conn, task_id, workdir)
            values["workdir"] = str(workdir)
            command = render_command(config["command"], values, "Runner command")
            if not workdir.is_dir():
                raise SwarmError("Runner working directory does not exist: %s" % workdir)
            if conn.execute("SELECT COUNT(*) FROM agent_runs WHERE ended_at IS NULL").fetchone()[
                0
            ] >= int(config.get("max_parallel", 3)):
                raise SwarmError("Harness concurrency limit reached")
            reason = budget_reason(conn)
            if reason:
                raise SwarmError(reason)
            if task_id:
                task = task_row(conn, task_id)
                require_owner(task, agent)
                generation = task["generation"]
                if conn.execute(
                    "SELECT 1 FROM agent_runs WHERE task_id=? AND ended_at IS NULL", (task_id,)
                ).fetchone():
                    raise SwarmError("Task already has an active harness run")
            else:
                generation = None
            m = mission(conn)
            conn.execute(
                """INSERT INTO agent_runs(id,mission_id,role,task_id,agent_id,prompt_path,command_json,started_at)
                            VALUES(?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    m["id"],
                    role,
                    task_id,
                    agent,
                    str(prompt_path),
                    json_dump(command),
                    utcnow(),
                ),
            )
            add_event(
                conn,
                m["id"],
                "agent_run",
                run_id,
                "AGENT_RUN_STARTED",
                "dispatcher",
                {
                    "role": role,
                    "agent_id": agent,
                    "task_id": task_id,
                    "generation": generation,
                    "model": model,
                    "prompt_sha256": hash_file(prompt_path)[0],
                    "workdir": str(workdir),
                },
            )
            conn.commit()
        finally:
            conn.close()
        timeout = int(config.get("timeout_seconds", 3600))
        stdout_path, stderr_path = run_dir / "stdout.txt", run_dir / "stderr.txt"
        exit_code = 126
        try:
            exit_code, _ = run_logged_process(
                command, workdir, timeout, stdout_path, stderr_path, run_lock
            )
        finally:
            conn = connect(root)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE agent_runs SET ended_at=?,exit_code=?,stdout_path=?,stderr_path=? WHERE id=?",
                    (utcnow(), exit_code, str(stdout_path), str(stderr_path), run_id),
                )
                add_event(
                    conn,
                    mission(conn)["id"],
                    "agent_run",
                    run_id,
                    "AGENT_RUN_FINISHED",
                    "dispatcher",
                    {
                        "exit_code": exit_code,
                        "role": role,
                        "task_id": task_id,
                        "generation": generation,
                        "model": model,
                    },
                )
                if task_id:
                    current = task_row(conn, task_id)
                    if (
                        current["owner"] == agent
                        and current["generation"] == generation
                        and current["status"] in ACTIVE_TASK_STATES
                    ):
                        end_attempt(
                            conn,
                            task_id,
                            "INCOMPLETE",
                            "Harness exited without completing or waiting",
                        )
                        conn.execute(
                            "UPDATE tasks SET status='READY',owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",
                            (utcnow(), task_id),
                        )
                        conn.execute(
                            "UPDATE effects SET state='UNKNOWN',updated_at=? WHERE task_id=? AND generation=? AND state='EXECUTING'",
                            (utcnow(), task_id, generation),
                        )
                        add_event(
                            conn,
                            mission(conn)["id"],
                            "task",
                            task_id,
                            "TASK_RUN_ENDED_INCOMPLETE",
                            "dispatcher",
                            {"agent_id": agent, "generation": generation, "exit_code": exit_code},
                        )
                conn.commit()
            finally:
                conn.close()
    return {
        "run_id": run_id,
        "exit_code": exit_code,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "model": model,
    }


def external_wait_summary(conn):
    active = [
        external_wait_dict(conn, row)
        for row in conn.execute(
            "SELECT * FROM external_waits WHERE status='WAITING' ORDER BY deadline_at"
        )
    ]
    deadline_attention = conn.execute(
        """SELECT COUNT(*) AS n FROM external_waits w JOIN tasks t ON t.id=w.task_id
           WHERE w.wake_reason='DEADLINE' AND t.status NOT IN ('DONE','CANCELLED')"""
    ).fetchone()["n"]
    checks = [item["next_check_at"] for item in active if item["next_check_at"]]
    deadlines = [item["deadline_at"] for item in active]
    return {
        "count": len(active),
        "earliest_scheduled_check": min(checks) if checks else None,
        "earliest_deadline": min(deadlines) if deadlines else None,
        "signal_expected_count": sum(1 for item in active if item["signal_expected"]),
        "deadline_attention_count": deadline_attention,
        "waits": active,
    }


def run_loop(root, max_cycles, dry_run=False):
    with process_lock(root / "controller.lock"):
        recovery = recover_runs(root, "controller")
        if recovery["live_or_unverified"]:
            return {"state": "RECOVERY_WAIT", "cycles": 0, "runs": [], "recovery": recovery}
        return _run_loop(root, max_cycles, dry_run)


def _run_loop(root, max_cycles, dry_run=False):
    """Run a bounded, event-responsive scheduling loop.

    A cycle is a scheduling turn that launches either one serialized manager
    review or a batch of workers. Existing harness processes count against the
    configured capacity until they exit, even if their task entered a wait.
    """
    config = runner_config(root)
    max_parallel = int(config.get("max_parallel", 3))
    lease_seconds = int(config.get("timeout_seconds", 3600)) + 300
    poll_seconds = float(config.get("scheduler_poll_seconds", 1))
    debounce_seconds = float(config.get("manager_review_debounce_seconds", 1))
    results = []
    cycles = 0

    conn = connect(root)
    try:
        reconcile_conn(conn)
        current_mission = mission(conn)
        if runtime_state(conn)["desired_state"] != "ACTIVE":
            return {"state": runtime_state(conn)["desired_state"], "cycles": 0, "runs": []}
        if current_mission["status"] == "DONE":
            return {
                "state": "DONE",
                "outcome": runtime_state(conn)["outcome"],
                "cycles": 0,
                "runs": results,
            }
        manager_runs = conn.execute(
            "SELECT COUNT(*) AS n FROM agent_runs WHERE role='manager'"
        ).fetchone()["n"]
        queued_review = conn.execute(
            "SELECT 1 FROM manager_reviews WHERE status IN ('PENDING','RUNNING') LIMIT 1"
        ).fetchone()
        if not manager_runs and not queued_review:
            request_manager_review(
                conn, "initial mission planning", "mission", current_mission["id"]
            )
            conn.commit()
    finally:
        conn.close()

    if dry_run:
        return {
            "state": "DRY_RUN",
            "cycles": 1,
            "runs": [dispatch(root, "manager", "manager", dry_run=True)],
        }

    active = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel)
    try:
        while True:
            completed = [future for future in active if future.done()]
            for future in completed:
                metadata = active.pop(future)
                try:
                    result = future.result()
                except (SwarmError, OSError, ValueError) as exc:
                    result = {"exit_code": 125, "error": str(exc)}
                    conn = connect(root)
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        if metadata.get("task_id"):
                            task = task_row(conn, metadata["task_id"])
                            if (
                                task["owner"] == metadata["agent"]
                                and task["status"] in ACTIVE_TASK_STATES
                            ):
                                end_attempt(conn, task["id"], "INCOMPLETE", str(exc))
                                conn.execute(
                                    "UPDATE tasks SET status='READY',owner=NULL,lease_until=NULL WHERE id=?",
                                    (task["id"],),
                                )
                        add_event(
                            conn,
                            mission(conn)["id"],
                            "mission",
                            mission(conn)["id"],
                            "DISPATCH_FAILED",
                            "controller",
                            {
                                "task_id": metadata.get("task_id"),
                                "agent": metadata["agent"],
                                "reason": str(exc),
                            },
                        )
                        conn.commit()
                    finally:
                        conn.close()
                results.append(result)
                if metadata["kind"] == "manager":
                    conn = connect(root)
                    try:
                        finish_manager_review(
                            conn,
                            metadata["review_id"],
                            metadata["agent"],
                            result.get("exit_code") == 0,
                        )
                    finally:
                        conn.close()

            conn = connect(root)
            try:
                reconcile_conn(conn)
                current_mission = mission(conn)
                if current_mission["status"] == "DONE" and not active:
                    return {
                        "state": "DONE",
                        "outcome": runtime_state(conn)["outcome"],
                        "cycles": cycles,
                        "runs": results,
                    }

                desired = runtime_state(conn)["desired_state"]
                exhausted = budget_reason(conn)
                if (desired != "ACTIVE" or exhausted) and not active:
                    if exhausted:
                        conn.execute(
                            "UPDATE runtime_state SET outcome='BUDGET_EXHAUSTED',reason=? WHERE id=1",
                            (exhausted,),
                        )
                        conn.commit()
                    return {
                        "state": "BUDGET_EXHAUSTED" if exhausted else desired,
                        "reason": exhausted,
                        "cycles": cycles,
                        "runs": results,
                    }
                if cycles >= max_cycles or desired != "ACTIVE" or exhausted:
                    if not active:
                        return {"state": "MAX_CYCLES", "cycles": cycles, "runs": results}
                    should_launch = False
                else:
                    # Manager reviews are serialized planning transactions. Existing
                    # workers may continue, but do not dispatch from a partially
                    # written plan before the manager process exits.
                    manager_active = any(
                        metadata["kind"] == "manager" for metadata in active.values()
                    )
                    should_launch = len(active) < max_parallel and not manager_active

                launched = False
                review_pending = False
                if should_launch:
                    review = claim_manager_review(
                        conn,
                        "manager",
                        lease_seconds,
                        debounce_seconds,
                    )
                    if review:
                        future = pool.submit(dispatch, root, "manager", "manager", None, False)
                        active[future] = {
                            "kind": "manager",
                            "agent": "manager",
                            "review_id": review["id"],
                        }
                        cycles += 1
                        launched = True
                    else:
                        review_pending = bool(
                            conn.execute(
                                "SELECT 1 FROM manager_reviews WHERE status='PENDING' LIMIT 1"
                            ).fetchone()
                        )

                if should_launch and not launched and not review_pending:
                    slots = max_parallel - len(active)
                    ready = conn.execute(
                        """SELECT * FROM tasks t WHERE status='READY'
                           AND NOT EXISTS (SELECT 1 FROM workspace_creations w WHERE w.task_id=t.id
                               AND w.state IN ('UNKNOWN','CREATED'))
                           ORDER BY priority DESC, created_at""",
                    ).fetchall()
                    assignments = []
                    for row in ready:
                        if len(assignments) >= slots:
                            break
                        agent = "worker-%s" % make_id("A")
                        try:
                            claim_task(conn, row["id"], agent, lease_seconds)
                        except SwarmError:
                            continue
                        assignments.append((role_for_task(row), agent, row["id"]))
                    if assignments:
                        for role, agent, task_id in assignments:
                            future = pool.submit(dispatch, root, role, agent, task_id, False)
                            active[future] = {
                                "kind": "worker",
                                "agent": agent,
                                "task_id": task_id,
                            }
                        cycles += 1
                        launched = True

                open_decisions = conn.execute(
                    "SELECT COUNT(*) AS n FROM decisions WHERE status='OPEN'"
                ).fetchone()["n"]
                waiting = external_wait_summary(conn)
                pending_reviews = conn.execute(
                    "SELECT COUNT(*) AS n FROM manager_reviews WHERE status='PENDING'"
                ).fetchone()["n"]
            finally:
                conn.close()

            if launched:
                continue
            if active:
                concurrent.futures.wait(
                    list(active),
                    timeout=poll_seconds,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                continue
            if pending_reviews and cycles < max_cycles:
                time.sleep(poll_seconds)
                continue
            if open_decisions:
                return {
                    "state": "WAITING_FOR_DECISION",
                    "cycles": cycles,
                    "runs": results,
                    "external_waits": waiting,
                }
            if waiting["count"]:
                return {
                    "state": "WAITING_EXTERNAL",
                    "cycles": cycles,
                    "runs": results,
                    "external_waits": waiting,
                }
            conn = connect(root)
            try:
                pending_workspaces = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT w.id,w.task_id,w.state FROM workspace_creations w JOIN tasks t ON t.id=w.task_id "
                        "WHERE w.state IN ('UNKNOWN','CREATED') AND t.status NOT IN ('DONE','CANCELLED') "
                        "ORDER BY w.created_at,w.id LIMIT 50"
                    )
                ]
                if pending_workspaces:
                    return {
                        "state": "WAITING_FOR_WORKSPACE",
                        "cycles": cycles,
                        "runs": results,
                        "workspace_creations": pending_workspaces,
                        "next_action": "Inspect workspace attempts --pending, reconcile provider outcomes, then attach with workspace create",
                    }
                exhausted_tasks = [
                    r["id"]
                    for r in conn.execute("SELECT id FROM tasks WHERE status='READY'")
                    if budget_reason(conn, r["id"])
                ]
                if exhausted_tasks:
                    if runtime_state(conn)["outcome"] != "ESCALATED":
                        conn.execute(
                            "UPDATE runtime_state SET outcome='ESCALATED',reason=? WHERE id=1",
                            ("Task retry budget exhausted",),
                        )
                        add_event(
                            conn,
                            mission(conn)["id"],
                            "mission",
                            mission(conn)["id"],
                            "SUPERVISOR_ESCALATED",
                            "supervisor",
                            {"tasks": exhausted_tasks},
                        )
                        conn.commit()
                    return {
                        "state": "ESCALATED",
                        "tasks": exhausted_tasks,
                        "cycles": cycles,
                        "runs": results,
                    }
            finally:
                conn.close()
            return {"state": "NO_READY_WORK", "cycles": cycles, "runs": results}
    finally:
        pool.shutdown(wait=True)


def recover_runs(root, actor="operator"):
    recovered, live = [], []
    conn = connect(root)
    try:
        unfinished = conn.execute("SELECT id FROM agent_runs WHERE ended_at IS NULL").fetchall()
        unfinished += conn.execute("SELECT id FROM delivery_runs WHERE ended_at IS NULL").fetchall()
        for row in unfinished:
            lockpath = root / "runs" / row["id"] / "process.lock"
            if not lockpath.exists():
                live.append(
                    {
                        "run_id": row["id"],
                        "reason": "legacy run; use recover --abandon-run only after confirming its process stopped",
                    }
                )
                continue
            try:
                with process_lock(lockpath):
                    abandon_run(
                        conn,
                        row["id"],
                        actor,
                        "Process lock released; harness no longer owns the run",
                    )
                    recovered.append(row["id"])
            except SwarmError:
                live.append({"run_id": row["id"], "reason": "process lock held"})
        reconcile_conn(conn)
        return {
            "recovered": recovered,
            "live_or_unverified": live,
            "uncertain_effects": [dict(x) for x in uncertain_effects(conn)],
            "uncertain_deliveries": [
                dict(x)
                for x in conn.execute(
                    "SELECT id,subject,last_error FROM deliveries WHERE status='UNKNOWN'"
                )
            ],
        }
    finally:
        conn.close()


@atomic_write
def abandon_run(conn, run_id, actor, reason):
    row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return abandon_delivery_run(conn, run_id, actor, reason)
    if row["ended_at"]:
        raise SwarmError("Run is already ended")
    conn.execute("UPDATE agent_runs SET ended_at=?,exit_code=125 WHERE id=?", (utcnow(), run_id))
    if row["role"] == "manager":
        for review in conn.execute(
            "SELECT id FROM manager_reviews WHERE status='RUNNING' AND owner=?", (row["agent_id"],)
        ).fetchall():
            conn.execute(
                "UPDATE manager_reviews SET status='PENDING',owner=NULL,lease_until=NULL,started_at=NULL,updated_at=? WHERE id=?",
                (utcnow(), review["id"]),
            )
            conn.execute("DELETE FROM review_commits WHERE review_id=?", (review["id"],))
            add_event(
                conn,
                row["mission_id"],
                "manager_review",
                review["id"],
                "MANAGER_REVIEW_INTERRUPTED",
                actor,
                {"run_id": run_id, "reason": reason},
            )
    if row["task_id"]:
        task = task_row(conn, row["task_id"])
        if task["owner"] == row["agent_id"] and task["status"] in ACTIVE_TASK_STATES:
            end_attempt(conn, task["id"], "INTERRUPTED", reason)
            conn.execute(
                "UPDATE tasks SET status='READY',owner=NULL,lease_until=NULL WHERE id=?",
                (task["id"],),
            )
        conn.execute(
            "UPDATE effects SET state='UNKNOWN',updated_at=? WHERE task_id=? AND state='EXECUTING'",
            (utcnow(), row["task_id"]),
        )
    add_event(
        conn,
        row["mission_id"],
        "agent_run",
        run_id,
        "AGENT_RUN_RECOVERED",
        actor,
        {"reason": reason, "task_id": row["task_id"]},
    )


def serve(root, max_polls, poll_seconds, max_cycles):
    if max_polls < 1 or poll_seconds <= 0:
        raise SwarmError("Service poll limits must be positive")
    with process_lock(root / "service.lock"):
        last = None
        for index in range(max_polls):
            last = run_loop(root, max_cycles)
            if last["state"] in {
                "DONE",
                "CANCELLED",
                "ABANDONED",
                "PAUSED",
                "BUDGET_EXHAUSTED",
                "ESCALATED",
            }:
                break
            if index + 1 < max_polls:
                time.sleep(poll_seconds)
        return {"polls": index + 1, "last": last}
