"""Register isolated checkouts or create them through an explicit provider."""

from pathlib import Path
import json
import os
import signal
import subprocess
import tempfile

from .core import ACTIVE_TASK_STATES, SwarmError, TERMINAL_TASK_STATES, atomic_write, process_lock
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
    if selected not in {"manual", "command", "git"}:
        raise SwarmError("Workspace provider must be manual, command, or git")
    value["provider"] = selected
    timeout = value.get("timeout_seconds", 300)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise SwarmError("Workspace timeout_seconds must be a positive integer")
    value["timeout_seconds"] = timeout
    if selected == "command":
        command = value.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) and x for x in command)
        ):
            raise SwarmError("Workspace command provider requires a nonempty argv array")
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
    return workspace_dict(
        conn.execute("SELECT * FROM workspaces WHERE task_id=?", (task_id,)).fetchone()
    )


def run_workspace_command(command, repository, timeout, lock_handle=None):
    # A failed/timeout adapter may have created a checkout. Never retry automatically
    # or delete its output: the operator can inspect and register it explicitly.
    try:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output, tempfile.TemporaryFile(
            mode="w+", encoding="utf-8"
        ) as errors:
            process = subprocess.Popen(
                command,
                cwd=str(repository),
                stdout=output,
                stderr=errors,
                start_new_session=True,
                pass_fds=(lock_handle.fileno(),) if lock_handle else (),
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                raise SwarmError(
                    "Workspace command timed out; inspect for a created checkout before retrying"
                )
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            errors.seek(0)
            if process.returncode:
                raise SwarmError(
                    "Workspace command failed; inspect before retrying: "
                    + errors.read(4000).strip()
                )
            output.seek(0)
            result = output.read(65537)
            if len(result) > 65536:
                raise SwarmError(
                    "Workspace command output exceeds 64KB; print one small JSON receipt"
                )
            return result
    except OSError as exc:
        raise SwarmError("Could not run workspace command: %s" % exc)


def create_workspace(root, conn, task_id, repository, base, provider=None, agent=None):
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
        if config["provider"] == "git":
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
            if resolved.returncode:
                raise SwarmError(
                    "Cannot resolve workspace base revision: " + resolved.stderr.strip()
                )
            revision = resolved.stdout.strip()
            reference = "codex/swarm-" + task_id.lower()
            run_workspace_command(
                [
                    "git",
                    "-C",
                    str(repository),
                    "worktree",
                    "add",
                    "-b",
                    reference,
                    str(path),
                    revision,
                ],
                repository,
                config["timeout_seconds"],
                lock_handle,
            )
        else:
            values = {
                "root": str(root),
                "repository": str(repository),
                "base": base,
                "path": str(path),
                "task_id": task_id,
            }
            try:
                command = [part.format(**values) for part in config["command"]]
            except (KeyError, ValueError, IndexError) as exc:
                raise SwarmError("Invalid workspace command placeholder: %s" % exc)
            raw = run_workspace_command(command, repository, config["timeout_seconds"], lock_handle)
            try:
                receipt = json.loads(raw)
            except ValueError:
                raise SwarmError(
                    "Workspace command must print a JSON object with path and base_revision; inspect any created checkout before retrying"
                )
            if (
                not isinstance(receipt, dict)
                or not isinstance(receipt.get("path"), str)
                or not Path(receipt["path"]).is_absolute()
            ):
                raise SwarmError("Workspace receipt requires an absolute path")
            path = Path(receipt["path"])
            revision = receipt.get("base_revision")
            reference = receipt.get("workspace_ref", "")
        # Recheck task state under a write lock after the external CLI returns.
        return register_workspace(
            conn,
            task_id,
            repository,
            path,
            revision,
            reference,
            config["provider"],
            agent=agent,
            requested_base=base,
        )
