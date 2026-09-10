"""Validate, install, and apply reusable task workflows."""

from pathlib import Path
import json
import hashlib

from .coordination import reconcile_conn
from .core import SwarmError, VALID_TASK_KINDS, atomic_write, json_dump, make_id, utcnow
from .queries import policy_application_dict, policy_pack_dict
from .storage import add_event, mission, require_task_capacity, workstream_row, stage_task


def validate_policy_manifest(manifest):
    if not isinstance(manifest, dict):
        raise SwarmError("Policy manifest must be a JSON object")
    if manifest.get("schema_version") != 1:
        raise SwarmError("Policy schema_version must be 1")
    for key in ("id", "version", "name", "description", "when_to_use"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise SwarmError("Policy %s must be a non-empty string" % key)
    policy_id = manifest["id"]
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in policy_id):
        raise SwarmError(
            "Policy id may contain only lowercase letters, digits, hyphens, and underscores"
        )
    variables = manifest.get("variables", {})
    if not isinstance(variables, dict):
        raise SwarmError("Policy variables must be an object")
    for name, specification in variables.items():
        if not isinstance(name, str) or not name or not isinstance(specification, dict):
            raise SwarmError("Each policy variable must have a name and object specification")
        if any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for character in name
        ):
            raise SwarmError(
                "Policy variable names may contain only letters, digits, and underscores"
            )
        if "required" in specification and not isinstance(specification["required"], bool):
            raise SwarmError("Policy variable %s required must be boolean" % name)
    stages = manifest.get("stages")
    if not isinstance(stages, list) or not stages:
        raise SwarmError("Policy must define at least one stage")
    seen = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise SwarmError("Each policy stage must be an object")
        for key in ("id", "title", "description", "kind", "acceptance"):
            if key not in stage:
                raise SwarmError("Policy stage is missing %s" % key)
        stage_id = stage["id"]
        if not isinstance(stage_id, str) or not stage_id or stage_id in seen:
            raise SwarmError("Policy stage ids must be unique non-empty strings")
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in stage_id):
            raise SwarmError(
                "Policy stage ids may contain only lowercase letters, digits, hyphens, and underscores"
            )
        for key in ("title", "description"):
            if not isinstance(stage[key], str) or not stage[key].strip():
                raise SwarmError("Policy stage %s %s must be a non-empty string" % (stage_id, key))
        if not isinstance(stage["kind"], str) or stage["kind"] not in VALID_TASK_KINDS:
            raise SwarmError("Policy stage %s has invalid task kind %s" % (stage_id, stage["kind"]))
        if (
            not isinstance(stage["acceptance"], list)
            or not stage["acceptance"]
            or not all(isinstance(item, str) and item.strip() for item in stage["acceptance"])
        ):
            raise SwarmError("Policy stage %s needs acceptance criteria" % stage_id)
        priority = stage.get("priority", 50)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise SwarmError("Policy stage %s priority must be an integer" % stage_id)
        dependencies = stage.get("depends_on", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(dep, str) or dep not in seen for dep in dependencies
        ):
            raise SwarmError("Policy stage %s dependencies must name earlier stages" % stage_id)
        fresh_from = stage.get("fresh_session_from", [])
        if isinstance(fresh_from, str):
            fresh_from = [fresh_from]
        if not isinstance(fresh_from, list) or any(
            not isinstance(item, str) or item not in seen for item in fresh_from
        ):
            raise SwarmError(
                "Policy stage %s fresh_session_from must name earlier stages" % stage_id
            )
        completion = stage.get("completion", {})
        if not isinstance(completion, dict):
            raise SwarmError("Policy stage %s completion must be an object" % stage_id)
        if "commitment_satisfied" in completion and not isinstance(
            completion["commitment_satisfied"], bool
        ):
            raise SwarmError("Policy completion commitment_satisfied must be boolean")
        minimum_artifacts = completion.get("minimum_artifacts", 0)
        if (
            not isinstance(minimum_artifacts, int)
            or isinstance(minimum_artifacts, bool)
            or minimum_artifacts < 0
        ):
            raise SwarmError(
                "Policy stage %s minimum_artifacts must be a non-negative integer" % stage_id
            )
        terms = completion.get("verification_terms", [])
        if not isinstance(terms, list) or any(
            not isinstance(term, str) or not term for term in terms
        ):
            raise SwarmError(
                "Policy stage %s verification_terms must be non-empty strings" % stage_id
            )
        if "artifact_files_required" in completion and not isinstance(
            completion["artifact_files_required"], bool
        ):
            raise SwarmError("Policy stage %s artifact_files_required must be boolean" % stage_id)
        sample_values = {name: "value" for name in variables}
        for location, template in [
            ("title", stage["title"]),
            ("description", stage["description"]),
        ] + [("acceptance", item) for item in stage["acceptance"]]:
            if not isinstance(template, str) or not template.strip():
                raise SwarmError(
                    "Policy stage %s %s must contain non-empty strings" % (stage_id, location)
                )
            try:
                template.format_map(sample_values)
            except (KeyError, ValueError, IndexError, AttributeError, TypeError) as exc:
                raise SwarmError(
                    "Policy stage %s %s has invalid variables: %s" % (stage_id, location, exc)
                )
        seen.add(stage_id)
    delivery = manifest.get("delivery")
    if delivery is not None:
        fields = {
            "producer_stage",
            "followup_stage",
            "title",
            "provider",
            "environment",
            "terminal_check",
            "responsible",
            "check_seconds",
            "deadline_seconds",
        }
        if not isinstance(delivery, dict) or set(delivery) != fields:
            raise SwarmError("Policy delivery requires " + ", ".join(sorted(fields)))
        if (
            not isinstance(delivery["producer_stage"], str)
            or not isinstance(delivery["followup_stage"], str)
            or delivery["producer_stage"] not in seen
            or delivery["followup_stage"] not in seen
            or delivery["producer_stage"] == delivery["followup_stage"]
        ):
            raise SwarmError("Delivery must reference distinct existing stages")
        for name in ("check_seconds", "deadline_seconds"):
            if (
                not isinstance(delivery[name], int)
                or isinstance(delivery[name], bool)
                or delivery[name] < 1
            ):
                raise SwarmError("Delivery intervals must be positive integers")
        if delivery["check_seconds"] > delivery["deadline_seconds"]:
            raise SwarmError("Delivery check must not exceed deadline")
        for name in fields - {
            "check_seconds",
            "deadline_seconds",
            "producer_stage",
            "followup_stage",
        }:
            if not isinstance(delivery[name], str) or not delivery[name].strip():
                raise SwarmError("Delivery requires nonempty " + name)
            render_policy_text(
                delivery[name], {name: "value" for name in variables}, "delivery." + name
            )
    return manifest


def read_policy_source(source):
    source_path = Path(source).expanduser().resolve()
    manifest_path = source_path / "policy.json" if source_path.is_dir() else source_path
    if not manifest_path.is_file():
        raise SwarmError("Policy manifest not found: %s" % manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SwarmError("Invalid policy JSON: %s" % exc)
    validate_policy_manifest(manifest)
    guidance_name = manifest.get("guidance", "GUIDANCE.md")
    if not isinstance(guidance_name, str) or not guidance_name:
        raise SwarmError("Policy guidance must be a relative file path")
    guidance_path_value = (manifest_path.parent / guidance_name).resolve()
    try:
        guidance_path_value.relative_to(manifest_path.parent.resolve())
    except ValueError:
        raise SwarmError("Policy guidance must stay inside the policy directory")
    if not guidance_path_value.is_file():
        raise SwarmError("Policy guidance not found: %s" % guidance_path_value)
    guidance = guidance_path_value.read_text(encoding="utf-8")
    if not guidance.strip():
        raise SwarmError("Policy guidance may not be empty")
    return manifest, guidance, manifest_path


@atomic_write
def install_policy(conn, source, actor, force=False):
    manifest, guidance, manifest_path = read_policy_source(source)
    existing = conn.execute("SELECT * FROM policy_packs WHERE id=?", (manifest["id"],)).fetchone()
    if existing and not force:
        raise SwarmError(
            "Policy %s is already installed at version %s; use --force to replace it"
            % (manifest["id"], existing["version"])
        )
    now = utcnow()
    conn.execute(
        """INSERT INTO policy_packs(id, version, name, description, when_to_use,
           manifest_json, guidance_text, source_path, installed_by, installed_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET version=excluded.version, name=excluded.name,
             description=excluded.description, when_to_use=excluded.when_to_use,
             manifest_json=excluded.manifest_json, guidance_text=excluded.guidance_text,
             source_path=excluded.source_path, installed_by=excluded.installed_by,
             installed_at=excluded.installed_at""",
        (
            manifest["id"],
            manifest["version"],
            manifest["name"],
            manifest["description"],
            manifest["when_to_use"],
            json_dump(manifest),
            guidance,
            str(manifest_path),
            actor,
            now,
        ),
    )
    current_mission = mission(conn)
    add_event(
        conn,
        current_mission["id"],
        "policy",
        manifest["id"],
        "POLICY_INSTALLED",
        actor,
        {
            "version": manifest["version"],
            "source_path": str(manifest_path),
            "replaced": bool(existing),
        },
    )
    return policy_pack_dict(
        conn, conn.execute("SELECT * FROM policy_packs WHERE id=?", (manifest["id"],)).fetchone()
    )


def parse_policy_variables(items):
    values = {}
    for item in items:
        if "=" not in item:
            raise SwarmError("Policy variables must use name=value: %s" % item)
        name, value = item.split("=", 1)
        if not name:
            raise SwarmError("Policy variable name may not be empty")
        if name in values:
            raise SwarmError("Policy variable was provided more than once: %s" % name)
        values[name] = value
    return values


def render_policy_text(value, variables, location):
    try:
        return value.format_map(variables)
    except (KeyError, ValueError, IndexError, AttributeError, TypeError) as exc:
        raise SwarmError("Could not render policy %s: %s" % (location, exc))


def prepare_policy(conn, policy_id, variable_items, workstream_id, ready):
    """Resolve one reviewed policy definition and canonical request fingerprint."""
    row = conn.execute("SELECT * FROM policy_packs WHERE id=?", (policy_id,)).fetchone()
    if not row:
        raise SwarmError("Unknown installed policy: %s" % policy_id)
    pack = policy_pack_dict(conn, row)
    manifest = pack["manifest"]
    values = parse_policy_variables(variable_items)
    specifications = manifest.get("variables", {})
    unknown = sorted(set(values) - set(specifications))
    if unknown:
        raise SwarmError("Unknown policy variables: %s" % ", ".join(unknown))
    for name, specification in specifications.items():
        if name not in values and "default" in specification:
            values[name] = str(specification["default"])
        if specification.get("required") and not values.get(name):
            raise SwarmError("Missing required policy variable: %s" % name)
    specification = hashlib.sha256(
        json_dump(
            {
                "policy_id": policy_id,
                "manifest": manifest,
                "guidance": pack["guidance_text"],
                "variables": values,
                "workstream_id": workstream_id,
                "ready": bool(ready),
            }
        ).encode("utf-8")
    ).hexdigest()
    return pack, values, specification


@atomic_write
def apply_policy(
    conn, policy_id, variable_items, workstream_id, actor, ready, idempotency_key=None
):
    """Create one atomic task graph, optionally deduplicated by a stable request key."""
    if idempotency_key is not None and not idempotency_key.strip():
        raise SwarmError("Policy idempotency key must not be empty")
    pack, values, specification = prepare_policy(
        conn, policy_id, variable_items, workstream_id, ready
    )
    manifest = pack["manifest"]
    if idempotency_key is not None:
        existing = conn.execute(
            "SELECT specification,application_id FROM policy_application_keys WHERE key=?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing["specification"] != specification:
                raise SwarmError("Policy idempotency key already belongs to different work")
            return policy_application_dict(conn, existing["application_id"])
    if workstream_id:
        stream = workstream_row(conn, workstream_id)
        if stream["status"] in {"DONE", "CANCELLED"}:
            raise SwarmError("Cannot apply a policy to a terminal workstream")

    rendered = []
    for stage in manifest["stages"]:
        rendered.append(
            {
                "stage": stage,
                "title": render_policy_text(stage["title"], values, "%s.title" % stage["id"]),
                "description": render_policy_text(
                    stage["description"], values, "%s.description" % stage["id"]
                ),
                "acceptance": [
                    render_policy_text(item, values, "%s.acceptance" % stage["id"])
                    for item in stage["acceptance"]
                ],
            }
        )

    current_mission = mission(conn)
    application_id = make_id("P")
    stage_tasks = {}
    require_task_capacity(conn, len(rendered))
    conn.execute(
        """INSERT INTO policy_applications(id, mission_id, policy_id, policy_version,
           manifest_json, guidance_text, variables_json, workstream_id, created_by, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            application_id,
            current_mission["id"],
            policy_id,
            pack["version"],
            json_dump(manifest),
            pack["guidance_text"],
            json_dump(values),
            workstream_id,
            actor,
            utcnow(),
        ),
    )
    if idempotency_key is not None:
        conn.execute(
            "INSERT INTO policy_application_keys(key,specification,application_id) VALUES(?,?,?)",
            (idempotency_key, specification, application_id),
        )
    for item in rendered:
        stage = item["stage"]
        dependencies = [stage_tasks[stage_id] for stage_id in stage.get("depends_on", [])]
        task_id = make_id("T")
        now = utcnow()
        conn.execute(
            """INSERT INTO tasks(id, mission_id, title, description, kind, priority,
               authorized, acceptance_json, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                current_mission["id"],
                item["title"],
                item["description"],
                stage["kind"],
                int(stage.get("priority", 50)),
                1 if ready else 0,
                json_dump(item["acceptance"]),
                now,
                now,
            ),
        )
        stage_task(conn, task_id, actor)
        for dependency in dependencies:
            conn.execute(
                "INSERT INTO task_dependencies(task_id, depends_on) VALUES(?,?)",
                (task_id, dependency),
            )
        if workstream_id:
            conn.execute(
                "INSERT INTO task_workstreams(task_id, workstream_id) VALUES(?,?)",
                (task_id, workstream_id),
            )
        conn.execute(
            """INSERT INTO policy_application_tasks(application_id, stage_id, task_id,
               fresh_session_from) VALUES(?,?,?,?)""",
            (
                application_id,
                stage["id"],
                task_id,
                json_dump(
                    [stage["fresh_session_from"]]
                    if isinstance(stage.get("fresh_session_from"), str)
                    else stage.get("fresh_session_from", [])
                ),
            ),
        )
        add_event(
            conn,
            current_mission["id"],
            "task",
            task_id,
            "TASK_PROPOSED",
            actor,
            {
                "title": item["title"],
                "kind": stage["kind"],
                "acceptance": item["acceptance"],
                "depends_on": dependencies,
                "authorized": bool(ready),
                "priority": int(stage.get("priority", 50)),
                "workstream_id": workstream_id,
                "policy_id": policy_id,
                "policy_application_id": application_id,
                "policy_stage_id": stage["id"],
            },
        )
        stage_tasks[stage["id"]] = task_id
    if manifest.get("delivery"):
        from .commitments import create_commitment
        from .core import future_time

        delivery = manifest["delivery"]
        specification = {
            name: render_policy_text(delivery[name], values, "delivery." + name)
            for name in ("title", "provider", "environment", "terminal_check", "responsible")
        }
        specification.update(
            producer_task=stage_tasks[delivery["producer_stage"]],
            followup_task=stage_tasks[delivery["followup_stage"]],
            next_check_at=future_time(delivery["check_seconds"]),
            deadline_at=future_time(delivery["deadline_seconds"]),
            signal_expected=True,
        )
        create_commitment(conn, specification, actor, "policy:" + application_id)
    add_event(
        conn,
        current_mission["id"],
        "policy_application",
        application_id,
        "POLICY_APPLIED",
        actor,
        {
            "policy_id": policy_id,
            "policy_version": pack["version"],
            "variables": values,
            "workstream_id": workstream_id,
            "tasks": stage_tasks,
            "idempotency_key": idempotency_key,
        },
    )
    reconcile_conn(conn)
    return policy_application_dict(conn, application_id)
