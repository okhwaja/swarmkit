"""Register isolated checkouts or create them through an explicit provider."""

from pathlib import Path
import json
import subprocess
import tempfile

from .config import WORKSPACE_FIELDS, render_command, validate_command
from .core import (
    ACTIVE_TASK_STATES,
    SwarmError,
    TERMINAL_TASK_STATES,
    atomic_write,
    process_lock,
    transaction,
    make_id,
    utcnow,
    json_dump,
    json_load,
    run_logged_process,
)
from .queries import workspace_dict
from .storage import add_event, require_owner, runtime_state, task_row


def workspace_config(root, provider=None):
    """Workspace setup is independent of the agent launch command."""
    path = root / "runner.json"
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(config, dict) or not isinstance(config.get("workspace", {}), dict):
        raise SwarmError("runner.json workspace must be an object")
    value = dict(config.get("workspace", {}))
    selected = provider or value.get("provider", "manual")
    if not isinstance(selected, str) or selected not in {"manual", "command", "git"}:
        raise SwarmError("Workspace provider must be manual, command, or git")
    value["provider"] = selected
    timeout = value.get("timeout_seconds", 300)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise SwarmError("Workspace timeout_seconds must be a positive integer")
    value["timeout_seconds"] = timeout
    if selected == "command":
        validate_command(value.get("command"), WORKSPACE_FIELDS, "Workspace command")
    return value


def workspace_task(conn, task_id, agent=None):
    task = task_row(conn, task_id)
    if task["status"] in TERMINAL_TASK_STATES:
        raise SwarmError("Cannot attach a workspace to a terminal task")
    if task["status"] in ACTIVE_TASK_STATES:
        if not agent:
            raise SwarmError("Active task workspace registration requires its --agent")
        require_owner(task, agent)
    if runtime_state(conn)["desired_state"] not in {"ACTIVE", "DRAINING"}:
        raise SwarmError("Mission is not accepting workspace changes")
    return task


@atomic_write
def register_workspace(
    conn,
    task_id,
    repository,
    path,
    base_revision,
    workspace_ref="",
    provider="manual",
    agent=None,
    requested_base=None,
    creation_id=None,
):
    task = workspace_task(conn, task_id, agent)
    if provider not in {"manual", "command", "git"}:
        raise SwarmError("Unknown workspace provider")
    if not isinstance(base_revision, str) or not base_revision.strip():
        raise SwarmError("Workspace requires an exact base revision identifier")
    if not isinstance(workspace_ref, str):
        raise SwarmError("Workspace reference must be a string")
    repository = Path(repository).expanduser().resolve()
    path = Path(path).expanduser().resolve()
    if not repository.is_dir() or not path.is_dir():
        raise SwarmError("Workspace source and checkout must be existing directories")
    if repository == path:
        raise SwarmError("An isolated workspace cannot be the source directory itself")
    existing = conn.execute("SELECT * FROM workspaces WHERE task_id=?", (task_id,)).fetchone()
    if existing:
        if (
            existing["repository"],
            existing["path"],
            existing["base_revision"],
            existing["branch"],
            existing["provider"],
        ) != (str(repository), str(path), base_revision, workspace_ref, provider):
            raise SwarmError(
                "Task already has a different workspace; existing registration is immutable"
            )
        return workspace_dict(existing)
    pending = pending_creation(conn, task_id)
    if pending and (pending["id"] != creation_id or pending["state"] != "CREATED"):
        raise SwarmError("Checkout creation requires reconciliation: " + pending["id"])
    if conn.execute("SELECT 1 FROM workspaces WHERE path=?", (str(path),)).fetchone():
        raise SwarmError("Checkout is already registered to another task")
    conn.execute(
        "INSERT INTO workspaces(task_id,path,repository,base_revision,branch,provider,requested_base) VALUES(?,?,?,?,?,?,?)",
        (
            task_id,
            str(path),
            str(repository),
            base_revision,
            workspace_ref,
            provider,
            requested_base,
        ),
    )
    add_event(
        conn,
        task["mission_id"],
        "task",
        task_id,
        "WORKSPACE_CREATED",
        agent or "operator",
        {
            "path": str(path),
            "repository": str(repository),
            "base_revision": base_revision,
            "workspace_ref": workspace_ref,
            "provider": provider,
            "requested_base": requested_base,
        },
    )
    if creation_id:
        update_creation(conn, creation_id, "REGISTERED", agent or "operator")
    return workspace_dict(
        conn.execute("SELECT * FROM workspaces WHERE task_id=?", (task_id,)).fetchone()
    )


def pending_creation(conn, task_id):
    return conn.execute(
        "SELECT * FROM workspace_creations WHERE task_id=? AND state IN ('UNKNOWN','CREATED')",
        (task_id,),
    ).fetchone()


def creation_dict(row):
    result = dict(row)
    result["command"] = json_load(result.pop("command_json"), [])
    result["receipt"] = json_load(result.pop("receipt_json"), None)
    return result


def creation_row(conn, creation_id):
    row = conn.execute("SELECT * FROM workspace_creations WHERE id=?", (creation_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown workspace creation: " + creation_id)
    return row


def validate_receipt(receipt):
    if (
        not isinstance(receipt, dict)
        or not isinstance(receipt.get("path"), str)
        or not Path(receipt["path"]).is_absolute()
    ):
        raise SwarmError("Workspace receipt requires an absolute path")
    if not isinstance(receipt.get("base_revision"), str) or not receipt["base_revision"].strip():
        raise SwarmError("Workspace receipt requires an exact base revision identifier")
    if not isinstance(receipt.get("workspace_ref", ""), str):
        raise SwarmError("Workspace reference must be a string")
    return {
        "path": str(Path(receipt["path"]).resolve()),
        "base_revision": receipt["base_revision"],
        "workspace_ref": receipt.get("workspace_ref", ""),
    }


@atomic_write
def update_creation(conn, creation_id, state, actor, receipt=None, observation=None):
    row = creation_row(conn, creation_id)
    conn.execute(
        "UPDATE workspace_creations SET state=?,receipt_json=COALESCE(?,receipt_json),"
        "observation=COALESCE(?,observation),updated_at=? WHERE id=?",
        (
            state,
            json_dump(receipt) if receipt is not None else None,
            observation,
            utcnow(),
            creation_id,
        ),
    )
    add_event(
        conn,
        task_row(conn, row["task_id"])["mission_id"],
        "task",
        row["task_id"],
        "WORKSPACE_CREATION_" + state,
        actor,
        {"creation_id": creation_id, "receipt": receipt, "observation": observation},
    )


def reconcile_workspace(
    root, conn, creation_id, outcome, observation, receipt=None, actor="operator"
):
    """Record provider-observed reality; a paused/cancelled mission may still be inspected."""
    if conn.in_transaction:
        raise SwarmError("Workspace reconciliation requires its own transaction")
    if outcome not in {"created", "not-created"}:
        raise SwarmError("Workspace outcome must be created or not-created")
    if not isinstance(observation, str) or not observation.strip():
        raise SwarmError("Workspace reconciliation requires a provider observation")
    if outcome == "created":
        receipt = validate_receipt(receipt)
        if not Path(receipt["path"]).is_dir():
            raise SwarmError("Observed checkout directory does not exist")
    elif receipt is not None:
        raise SwarmError("A not-created outcome cannot include a checkout receipt")
    state = "CREATED" if outcome == "created" else "NOT_CREATED"
    # A surviving adapter inherits this lock. A timeout/expired task lease cannot
    # authorize a second creation while the old process still owns it.
    with process_lock(root / "workspaces.lock"), transaction(conn):
        row = creation_row(conn, creation_id)
        same_outcome = row["state"] == state or (
            row["state"] == "REGISTERED" and state == "CREATED"
        )
        if same_outcome and json_load(row["receipt_json"], None) == receipt:
            return creation_dict(row)
        if row["state"] != "UNKNOWN":
            raise SwarmError("Only an uncertain creation can be reconciled")
        if receipt and Path(receipt["path"]).resolve() == Path(row["repository"]).resolve():
            raise SwarmError("An isolated workspace cannot be the source directory itself")
        update_creation(conn, creation_id, state, actor, receipt, observation)
        return creation_dict(creation_row(conn, creation_id))


def read_command_receipt(stdout_path):
    with stdout_path.open(encoding="utf-8", errors="replace") as output:
        raw = output.read(65537)
    if len(raw) > 65536:
        raise SwarmError("Workspace command output exceeds 64KB; print one small JSON receipt")
    try:
        return validate_receipt(json.loads(raw))
    except ValueError:
        raise SwarmError("Workspace command must print a JSON object with path and base_revision")


def run_workspace_command(command, repository, timeout, lock_handle=None):
    """Compatibility helper for an explicitly owned, bounded provider invocation."""
    with tempfile.TemporaryDirectory(prefix="swarm-checkout-") as directory:
        root = Path(directory)
        if lock_handle is None:
            with process_lock(root / "command.lock") as handle:
                return run_workspace_command(command, repository, timeout, handle)
        output, errors = root / "stdout", root / "stderr"
        code, _ = run_logged_process(command, repository, timeout, output, errors, lock_handle)
        if code:
            raise SwarmError("Workspace command failed; inspect before retrying")
        with output.open(encoding="utf-8") as stream:
            result = stream.read(65537)
        if len(result) > 65536:
            raise SwarmError("Workspace command output exceeds 64KB")
        return result


@atomic_write
def attach_created_workspace(conn, row, agent):
    receipt = json_load(row["receipt_json"])
    return register_workspace(
        conn,
        row["task_id"],
        row["repository"],
        receipt["path"],
        receipt["base_revision"],
        receipt["workspace_ref"],
        row["provider"],
        agent=agent,
        requested_base=row["requested_base"],
        creation_id=row["id"],
    )


def create_workspace(root, conn, task_id, repository, base, provider=None, agent=None):
    if conn.in_transaction:
        raise SwarmError(
            "Workspace creation requires its own transaction before running a provider"
        )
    workspace_task(conn, task_id, agent)
    config = workspace_config(root, provider)
    repository = Path(repository).expanduser().resolve()
    if not repository.is_dir() or not isinstance(base, str) or not base.strip():
        raise SwarmError(
            "Workspace creation requires an existing source directory and base revision"
        )
    with process_lock(root / "workspaces.lock") as lock_handle:
        workspace_task(conn, task_id, agent)
        existing = conn.execute("SELECT * FROM workspaces WHERE task_id=?", (task_id,)).fetchone()
        if existing:
            if (
                existing["repository"] != str(repository)
                or existing["provider"] != config["provider"]
            ):
                raise SwarmError("Task already has a workspace from a different source or provider")
            if existing["requested_base"] is not None and existing["requested_base"] != base:
                raise SwarmError("Task workspace was created with a different base request")
            if not Path(existing["path"]).is_dir():
                raise SwarmError("Registered workspace is missing; restore it before dispatch")
            return workspace_dict(existing)
        pending = pending_creation(conn, task_id)
        if pending:
            if pending["state"] == "UNKNOWN":
                raise SwarmError("Checkout creation requires reconciliation: " + pending["id"])
            if (pending["repository"], pending["provider"], pending["requested_base"]) != (
                str(repository),
                config["provider"],
                base,
            ):
                raise SwarmError("Recovered checkout belongs to a different creation request")
            return attach_created_workspace(conn, pending, agent)
        if config["provider"] == "manual":
            raise SwarmError(
                "No workspace creation provider configured. Register a harness-created checkout with workspace register, configure workspace.provider=command, or select --provider git"
            )
        path = root / "workspaces" / task_id
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SwarmError(
                "Unregistered workspace path already exists; inspect and register it before retrying"
            )
        receipt = None
        if config["provider"] == "git":
            try:
                resolved = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repository),
                        "rev-parse",
                        "--verify",
                        "--end-of-options",
                        base + "^{commit}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=config["timeout_seconds"],
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise SwarmError("Cannot resolve workspace base revision: " + str(exc))
            if resolved.returncode:
                raise SwarmError(
                    "Cannot resolve workspace base revision: " + resolved.stderr.strip()
                )
            revision, reference = resolved.stdout.strip(), "codex/swarm-" + task_id.lower()
            command = [
                "git",
                "-C",
                str(repository),
                "worktree",
                "add",
                "-b",
                reference,
                str(path),
                revision,
            ]
            receipt = {"path": str(path), "base_revision": revision, "workspace_ref": reference}
        else:
            values = {
                "root": str(root),
                "repository": str(repository),
                "base": base,
                "path": str(path),
                "task_id": task_id,
            }
            command = render_command(config["command"], values, "Workspace command")
        creation_id = make_id("WC")
        log_dir = root / "runs" / "workspaces" / creation_id
        log_dir.mkdir(parents=True)
        stdout, stderr = log_dir / "stdout.log", log_dir / "stderr.log"
        # Commit ambiguity before the external action. Even a crash between this
        # commit and Popen requires observation, never a guessed replay.
        with transaction(conn):
            task = workspace_task(conn, task_id, agent)
            if conn.execute("SELECT 1 FROM workspaces WHERE task_id=?", (task_id,)).fetchone():
                raise SwarmError("Task acquired a workspace while creation was being prepared")
            now = utcnow()
            conn.execute(
                "INSERT INTO workspace_creations(id,task_id,repository,requested_base,provider,"
                "suggested_path,state,command_json,stdout_path,stderr_path,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'UNKNOWN',?,?,?,?,?)",
                (
                    creation_id,
                    task_id,
                    str(repository),
                    base,
                    config["provider"],
                    str(path),
                    json_dump(command),
                    str(stdout),
                    str(stderr),
                    now,
                    now,
                ),
            )
            add_event(
                conn,
                task["mission_id"],
                "task",
                task_id,
                "WORKSPACE_CREATION_STARTED",
                agent or "operator",
                {"creation_id": creation_id, "provider": config["provider"]},
            )
        code, started = run_logged_process(
            command, repository, config["timeout_seconds"], stdout, stderr, lock_handle
        )
        if not started:
            update_creation(
                conn,
                creation_id,
                "NOT_CREATED",
                "runtime",
                observation="Provider process could not start",
            )
        if code:
            with stderr.open(encoding="utf-8", errors="replace") as errors:
                detail = errors.read(4000).strip()
            reason = "timed out" if code == 124 else "failed"
            raise SwarmError(
                "Workspace command " + reason + ": " + detail + "; inspect creation " + creation_id
            )
        receipt = validate_receipt(receipt) if receipt else read_command_receipt(stdout)
        # Preserve a valid provider receipt even when pause/lease expiry prevents
        # attachment. A later eligible owner can attach it without invoking again.
        if not Path(receipt["path"]).is_dir() or Path(receipt["path"]) == repository:
            raise SwarmError(
                "Workspace receipt must identify an existing isolated checkout; inspect creation "
                + creation_id
            )
        update_creation(conn, creation_id, "CREATED", "runtime", receipt=receipt)
        return attach_created_workspace(conn, creation_row(conn, creation_id), agent)
