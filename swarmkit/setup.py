"""Initialize a mission and check that its harness and workspace are usable."""

from pathlib import Path
import json
import os
import shutil
import sqlite3
import tempfile

from .config import runner_config
from .core import (
    PACKAGE_ROOT,
    SCHEMA_VERSION,
    SwarmError,
    VALID_MISSION_MODES,
    VERSION,
    db_path,
    json_dump,
    make_id,
    process_lock,
    transaction,
    utcnow,
)
from .delivery import read_extension_source
from .diagnostics import doctor
from .policies import read_policy_source
from .runtime import dispatch
from .schema import (
    EVIDENCE_SCHEMA,
    migrate_coordination,
    migrate_reliability_schema,
    migrate_review_batches,
    RUNTIME_SCHEMA,
    WORKSPACE_CREATION_SCHEMA,
    SCHEMA,
    execute_schema,
    migrate_workspace_schema,
)
from .storage import add_event, connect, mission
from .views import render_board
from .workspaces import workspace_config


def initialize(root, objective, success, constraints, mode="FINITE"):
    mode = mode.upper()
    if mode not in VALID_MISSION_MODES:
        raise SwarmError("Invalid mission mode: %s" % mode)
    if not objective.strip():
        raise SwarmError("Mission objective must not be empty")
    root.mkdir(parents=True, exist_ok=True)
    with process_lock(root / ".init.lock"):
        if db_path(root).exists():
            raise SwarmError("Workspace already exists at %s" % root)
        for name in ("prompts", "runs", "views", "outbox", "intake"):
            (root / name).mkdir(exist_ok=True)
        # Publish only a complete, closed database. A crash or failed transaction
        # cannot leave a half-initialized mission at the canonical path.
        with tempfile.TemporaryDirectory(prefix=".initialize-", dir=str(root)) as staging:
            staging_root = Path(staging)
            conn = connect(staging_root, require=False)
            try:
                with transaction(conn):
                    execute_schema(conn, SCHEMA)
                    execute_schema(conn, RUNTIME_SCHEMA)
                    migrate_workspace_schema(conn)
                    migrate_reliability_schema(conn)
                    execute_schema(conn, WORKSPACE_CREATION_SCHEMA)
                    migrate_review_batches(conn)
                    execute_schema(conn, EVIDENCE_SCHEMA)
                    migrate_coordination(conn)
                    from .schema import migrate_delivery_contracts

                    migrate_delivery_contracts(conn)
                    now = utcnow()
                    mission_id = make_id("M")
                    conn.execute(
                        "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                        (SCHEMA_VERSION,),
                    )
                    conn.execute(
                        "INSERT INTO meta(key, value) VALUES('swarmctl_version', ?)", (VERSION,)
                    )
                    conn.execute("INSERT INTO meta(key, value) VALUES('mission_mode', ?)", (mode,))
                    conn.execute(
                        "INSERT INTO missions(id, objective, success_json, constraints_json, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                        (
                            mission_id,
                            objective,
                            json_dump(success),
                            json_dump(constraints),
                            now,
                            now,
                        ),
                    )
                    add_event(
                        conn,
                        mission_id,
                        "mission",
                        mission_id,
                        "MISSION_CREATED",
                        "human",
                        {"objective": objective, "success": success, "constraints": constraints},
                    )
            finally:
                conn.close()
            config_path = root / "runner.json"
            if not config_path.exists():
                with config_path.open("x", encoding="utf-8") as handle:
                    handle.write(json.dumps(default_runner(root), indent=2) + "\n")
            os.replace(str(db_path(staging_root)), str(db_path(root)))
    render_board(root)
    return mission_id


def default_runner(root):
    """A harness-neutral starting point; checkout creation is always explicit."""
    return {
        "command": [],
        "working_directory": str(root.parent),
        "workspace": {"provider": "manual"},
        "max_parallel": 3,
        "timeout_seconds": 3600,
        "scheduler_poll_seconds": 1,
        "manager_review_debounce_seconds": 1,
        "models": {
            "manager": "",
            "worker": "",
            "briefer": "",
            "extension": "",
            "verifier": "",
        },
        "notes": "Set command to an argv array accepted by your harness. Available placeholders: {prompt_file}, {role}, {task_id}, {agent_id}, {root}, {workdir}, {model}.",
    }


def setup_check(root):
    """Validate a local harness adapter without launching the harness."""
    checks = []
    errors = []
    warnings = []

    def record(name, ok, detail, severity="error"):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            (errors if severity == "error" else warnings).append(detail)

    database_ready = False
    if not db_path(root).exists():
        record("mission_state", False, "Mission state is missing; run swarmctl init first")
    else:
        try:
            conn = connect(root)
            try:
                current = mission(conn)
                state_health = doctor(conn)
                schema = conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'"
                ).fetchone()
                database_ready = True
                record(
                    "mission_state",
                    True,
                    "Mission %s is readable with schema %s"
                    % (
                        current["id"],
                        schema["value"] if schema else "unknown",
                    ),
                )
                state_errors = [
                    item for item in state_health["problems"] if item["severity"] == "error"
                ]
                record(
                    "state_invariants",
                    not state_errors,
                    (
                        "Canonical state has no invariant errors"
                        if not state_errors
                        else "Canonical state has invariant errors: %s"
                        % "; ".join(
                            "%s: %s" % (item["entity"], item["problem"]) for item in state_errors
                        )
                    ),
                )
                for item in state_health["problems"]:
                    if item["severity"] == "warning":
                        warnings.append(
                            "State warning for %s: %s" % (item["entity"], item["problem"])
                        )
            finally:
                conn.close()
        except (SwarmError, sqlite3.Error, OSError) as exc:
            record("mission_state", False, "Mission state could not be read: %s" % exc)

    config_path = root / "runner.json"
    config = None
    if not config_path.exists():
        record("runner_config", False, "Runner config is missing: %s" % config_path)
    else:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            record("runner_config", isinstance(config, dict), "Runner config is valid JSON object")
            if not isinstance(config, dict):
                config = None
        except (json.JSONDecodeError, OSError) as exc:
            record("runner_config", False, "Runner config is invalid: %s" % exc)

    command = config.get("command") if config else None
    try:
        runner_config(root)
        record("runner_contract", True, "Runner templates, models, and limits are valid")
    except (SwarmError, ValueError, OSError) as exc:
        record("runner_contract", False, str(exc))
    command_valid = (
        isinstance(command, list)
        and bool(command)
        and all(isinstance(part, str) and part for part in command)
    )
    record(
        "command_argv",
        command_valid,
        (
            "Runner command is a non-empty argv array"
            if command_valid
            else "Runner command must be a non-empty array of non-empty strings"
        ),
    )

    if command_valid:
        has_prompt = any("{prompt_file}" in part for part in command)
        record(
            "prompt_delivery",
            has_prompt,
            (
                "Runner command includes {prompt_file}"
                if has_prompt
                else "Runner command must include {prompt_file} so every role receives its generated prompt"
            ),
        )
        executable = command[0]
        executable_path = None
        if "{" in executable or "}" in executable:
            executable_detail = (
                "Runner executable may not contain dynamic placeholders: %s" % executable
            )
        elif Path(executable).is_absolute() or os.sep in executable:
            configured_value = config.get("working_directory")
            configured_workdir = (
                Path(configured_value).expanduser().resolve()
                if isinstance(configured_value, str) and configured_value
                else root.parent
            )
            candidate = Path(executable).expanduser()
            executable_path = (
                candidate if candidate.is_absolute() else configured_workdir / candidate
            )
            executable_detail = "Resolved runner executable: %s" % executable_path
        else:
            found = shutil.which(executable)
            executable_path = Path(found) if found else None
            executable_detail = (
                "Resolved runner executable: %s" % found
                if found
                else "Runner executable is not available on PATH: %s" % executable
            )
        executable_ok = bool(
            executable_path
            and executable_path.is_file()
            and os.access(str(executable_path), os.X_OK)
        )
        record("runner_executable", executable_ok, executable_detail)
        shell_names = {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "pwsh"}
        direct_shell = Path(executable).name.lower() in shell_names
        record(
            "no_shell_interpolation",
            not direct_shell,
            (
                "Runner invokes an executable directly"
                if not direct_shell
                else "Runner command may not invoke a shell directly; use a fixed adapter executable"
            ),
        )
    else:
        record(
            "prompt_delivery",
            False,
            "Prompt delivery cannot be checked until command_argv is fixed",
        )
        record(
            "runner_executable",
            False,
            "Runner executable cannot be checked until command_argv is fixed",
        )
        record(
            "no_shell_interpolation",
            False,
            "Shell use cannot be checked until command_argv is fixed",
        )

    try:
        workspace = workspace_config(root)
        record(
            "workspace_provider",
            True,
            "Workspace provider: "
            + workspace["provider"]
            + " (creation is explicit; no checkout command was run)",
        )
    except (SwarmError, OSError, ValueError) as exc:
        record("workspace_provider", False, str(exc))

    workdir_value = config.get("working_directory") if config else None
    if workdir_value is not None and not isinstance(workdir_value, str):
        workdir = root.parent
        workdir_detail = "working_directory must be a string"
        workdir_ok = False
    elif not workdir_value:
        workdir = root.parent
        workdir_detail = "Runner uses mission parent as working directory: %s" % workdir
        workdir_ok = workdir.is_dir() and os.access(str(workdir), os.R_OK | os.X_OK)
    else:
        raw_workdir = Path(workdir_value).expanduser()
        workdir = raw_workdir.resolve()
        workdir_detail = "Runner working directory: %s" % workdir
        if not raw_workdir.is_absolute():
            warnings.append("Use an absolute working_directory to avoid launch-directory ambiguity")
        workdir_ok = workdir.is_dir() and os.access(str(workdir), os.R_OK | os.X_OK)
    record("working_directory", workdir_ok, workdir_detail)

    timeout = config.get("timeout_seconds", 3600) if config else None
    timeout_ok = isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 0
    record(
        "timeout",
        timeout_ok,
        (
            "Runner timeout is %s seconds" % timeout
            if timeout_ok
            else "timeout_seconds must be a positive integer"
        ),
    )

    max_parallel = config.get("max_parallel", 3) if config else None
    max_parallel_ok = (
        isinstance(max_parallel, int) and not isinstance(max_parallel, bool) and max_parallel > 0
    )
    record(
        "max_parallel",
        max_parallel_ok,
        (
            "Runner permits up to %s concurrent agent processes" % max_parallel
            if max_parallel_ok
            else "max_parallel must be a positive integer"
        ),
    )

    scheduler_poll = config.get("scheduler_poll_seconds", 1) if config else None
    scheduler_poll_ok = (
        isinstance(scheduler_poll, (int, float))
        and not isinstance(scheduler_poll, bool)
        and scheduler_poll > 0
    )
    record(
        "scheduler_poll_seconds",
        scheduler_poll_ok,
        (
            "Responsive scheduler polls durable events every %s second(s)" % scheduler_poll
            if scheduler_poll_ok
            else "scheduler_poll_seconds must be a positive number"
        ),
    )
    manager_debounce = config.get("manager_review_debounce_seconds", 1) if config else None
    manager_debounce_ok = (
        isinstance(manager_debounce, (int, float))
        and not isinstance(manager_debounce, bool)
        and manager_debounce >= 0
    )
    record(
        "manager_review_debounce_seconds",
        manager_debounce_ok,
        (
            "Nearby normal manager triggers coalesce for %s second(s)" % manager_debounce
            if manager_debounce_ok
            else "manager_review_debounce_seconds must be a non-negative number"
        ),
    )

    models = config.get("models", {}) if config else None
    models_ok = isinstance(models, dict) and all(
        isinstance(role, str) and isinstance(model, str) for role, model in models.items()
    )
    record(
        "model_mapping",
        models_ok,
        (
            "Runner model mapping is valid"
            if models_ok
            else "models must be an object whose keys and values are strings"
        ),
    )

    package_root = PACKAGE_ROOT
    required_guidance = [
        "manager.md",
        "worker.md",
        "briefer.md",
        "verifier.md",
        "liaison.md",
        "status.md",
        "HARNESS_SYSTEM_PROMPT.md",
    ]
    missing_guidance = [
        name for name in required_guidance if not (package_root / "guidance" / name).is_file()
    ]
    record(
        "role_guidance",
        not missing_guidance,
        (
            "All required role guidance is present"
            if not missing_guidance
            else "Missing role guidance: %s" % ", ".join(missing_guidance)
        ),
    )
    example_policies = sorted((package_root / "examples" / "policy-packs").glob("*/policy.json"))
    try:
        validated_policies = []
        for policy_path in example_policies:
            example_manifest, _, _ = read_policy_source(policy_path.parent)
            validated_policies.append(
                "%s@%s"
                % (
                    example_manifest["id"],
                    example_manifest["version"],
                )
            )
        if not validated_policies:
            raise SwarmError("No bundled policy packs found")
        record(
            "policy_pack_support",
            True,
            "Bundled policies are valid: %s" % ", ".join(validated_policies),
        )
    except (SwarmError, OSError) as exc:
        record("policy_pack_support", False, "Bundled policy validation failed: %s" % exc)
    example_extension = package_root / "examples" / "extensions" / "harness-email"
    try:
        extension_manifest, _, _ = read_extension_source(example_extension)
        record(
            "delivery_extension_support",
            True,
            "Bundled extension %s@%s is valid"
            % (extension_manifest["id"], extension_manifest["version"]),
        )
    except (SwarmError, OSError) as exc:
        record("delivery_extension_support", False, "Bundled extension validation failed: %s" % exc)

    prerequisite_checks = {item["name"]: item["ok"] for item in checks}
    dry_run_ready = database_ready and all(
        prerequisite_checks.get(name, False)
        for name in (
            "runner_config",
            "command_argv",
            "prompt_delivery",
            "runner_executable",
            "no_shell_interpolation",
            "working_directory",
            "timeout",
            "max_parallel",
            "scheduler_poll_seconds",
            "manager_review_debounce_seconds",
            "model_mapping",
            "role_guidance",
            "policy_pack_support",
            "delivery_extension_support",
        )
    )
    if dry_run_ready:
        try:
            result = dispatch(root, "manager", "setup-check-manager", dry_run=True)
            prompt_path = Path(result["prompt_path"])
            record(
                "prompt_dry_run",
                prompt_path.is_file(),
                "Generated manager prompt and expanded argv at %s" % prompt_path,
            )
        except (
            SwarmError,
            OSError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            record("prompt_dry_run", False, "Dry-run prompt generation failed: %s" % exc)
    else:
        record(
            "prompt_dry_run",
            False,
            "Dry-run prompt generation skipped until earlier setup errors are fixed",
        )

    warnings.extend(
        [
            "Static checks cannot prove that the harness starts a fresh model context; run the playbook's fresh-context test",
            "Static checks cannot prove agent CLI permissions, exit-code forwarding, authentication, or concurrent invocation behavior",
        ]
    )
    return {"ok": not errors, "checks": checks, "errors": errors, "warnings": warnings}
