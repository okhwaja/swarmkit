"""Export and verify portable mission audit bundles."""

from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import textwrap
import zipfile

from .core import consistent_read
from .core import PACKAGE_ROOT, VERSION, hash_file, json_load, parse_time, utcnow, SwarmError
from .diagnostics import doctor
from .queries import explain_state, mission_snapshot
from .storage import connect, runtime_state
from .views import render_board


@consistent_read
def audit_summary(conn, snapshot=None):
    snap = snapshot if snapshot is not None else mission_snapshot(conn)
    counts = {}
    for task in snap["tasks"]:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    policy_counts = {}
    for application in snap["policy_applications"]:
        policy_counts[application["status"]] = policy_counts.get(application["status"], 0) + 1
    delivery_counts = {}
    for delivery in snap["deliveries"]:
        delivery_counts[delivery["status"]] = delivery_counts.get(delivery["status"], 0) + 1
    case_counts = {}
    for case in snap["cases"]:
        case_counts[case["status"]] = case_counts.get(case["status"], 0) + 1
    finding_counts = {}
    for finding in snap["findings"]:
        key = "%s:%s" % (finding["significance"], finding["status"])
        finding_counts[key] = finding_counts.get(key, 0) + 1
    wait_counts = {}
    wake_reason_counts = {}
    wait_durations = []
    for wait in snap["external_waits"]:
        wait_counts[wait["status"]] = wait_counts.get(wait["status"], 0) + 1
        if wait["wake_reason"]:
            wake_reason_counts[wait["wake_reason"]] = (
                wake_reason_counts.get(wait["wake_reason"], 0) + 1
            )
        if wait["woke_at"]:
            wait_durations.append(
                (parse_time(wait["woke_at"]) - parse_time(wait["created_at"])).total_seconds()
            )
    workstream_counts = {}
    forecast_outcomes = []
    for workstream in snap["workstreams"]:
        workstream_counts[workstream["status"]] = workstream_counts.get(workstream["status"], 0) + 1
        if workstream["status"] == "DONE" and workstream["forecast_latest"]:
            forecast_outcomes.append(
                {
                    "workstream_id": workstream["id"],
                    "name": workstream["name"],
                    "latest_forecast": workstream["forecast_latest"],
                    "completed_at": workstream["updated_at"],
                    "seconds_after_latest_forecast": round(
                        (
                            parse_time(workstream["updated_at"])
                            - parse_time(workstream["forecast_latest"])
                        ).total_seconds(),
                        3,
                    ),
                }
            )
    events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    runs = conn.execute("SELECT COUNT(*) AS n FROM agent_runs").fetchone()["n"]
    failed_runs = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_runs WHERE exit_code IS NOT NULL AND exit_code <> 0"
    ).fetchone()["n"]
    unacked = conn.execute(
        """SELECT COUNT(*) AS n FROM decision_tasks dt JOIN decisions d ON d.id=dt.decision_id
           LEFT JOIN decision_acks a ON a.decision_id=d.id AND a.task_id=dt.task_id
           WHERE d.status='RESOLVED' AND (a.version IS NULL OR a.version < d.version)"""
    ).fetchone()["n"]
    event_type_counts = {
        row["event_type"]: row["n"]
        for row in conn.execute(
            "SELECT event_type, COUNT(*) AS n FROM events GROUP BY event_type ORDER BY event_type"
        )
    }
    decision_resolution_seconds = []
    for row in conn.execute(
        "SELECT created_at, decided_at FROM decisions WHERE decided_at IS NOT NULL"
    ):
        decision_resolution_seconds.append(
            (parse_time(row["decided_at"]) - parse_time(row["created_at"])).total_seconds()
        )
    decision_ack_seconds = []
    for row in conn.execute(
        """SELECT d.decided_at, a.acknowledged_at FROM decision_acks a
           JOIN decisions d ON d.id=a.decision_id WHERE d.decided_at IS NOT NULL"""
    ):
        decision_ack_seconds.append(
            (parse_time(row["acknowledged_at"]) - parse_time(row["decided_at"])).total_seconds()
        )
    task_cycle_seconds = []
    for row in conn.execute(
        "SELECT created_at, updated_at FROM tasks WHERE status IN ('DONE','CANCELLED')"
    ):
        task_cycle_seconds.append(
            (parse_time(row["updated_at"]) - parse_time(row["created_at"])).total_seconds()
        )
    manager_review_latency_seconds = []
    for row in conn.execute(
        "SELECT requested_at, started_at FROM manager_reviews WHERE started_at IS NOT NULL"
    ):
        manager_review_latency_seconds.append(
            (parse_time(row["started_at"]) - parse_time(row["requested_at"])).total_seconds()
        )

    def duration_stats(values):
        if not values:
            return {"count": 0, "average_seconds": None, "maximum_seconds": None}
        return {
            "count": len(values),
            "average_seconds": round(sum(values) / len(values), 3),
            "maximum_seconds": round(max(values), 3),
        }

    return {
        "task_counts": counts,
        "workstream_counts": workstream_counts,
        "policy_application_counts": policy_counts,
        "case_counts": case_counts,
        "finding_counts": finding_counts,
        "external_wait_counts": wait_counts,
        "external_wait_wake_reasons": wake_reason_counts,
        "delivery_counts": delivery_counts,
        "completed_workstream_forecast_outcomes": forecast_outcomes,
        "event_count": events,
        "agent_run_count": runs,
        "failed_agent_runs": failed_runs,
        "unacknowledged_resolved_decisions": unacked,
        "event_type_counts": event_type_counts,
        "decision_resolution_latency": duration_stats(decision_resolution_seconds),
        "decision_ack_latency": duration_stats(decision_ack_seconds),
        "manager_review_latency": duration_stats(manager_review_latency_seconds),
        "external_wait_duration": duration_stats(wait_durations),
        "terminal_task_cycle_time": duration_stats(task_cycle_seconds),
        "doctor": doctor(conn),
    }


def stage_private_audit(root, source_root, stage, include_artifacts=False, max_artifact_mb=25):
    render_board(root, reconcile=False)
    conn = connect(root)
    try:
        snapshot = mission_snapshot(conn)
        with (stage / "events.jsonl").open("w", encoding="utf-8") as event_file:
            for row in conn.execute("SELECT * FROM events ORDER BY seq"):
                data = dict(row)
                data["payload"] = json_load(data.pop("payload_json"), {})
                event_file.write(json.dumps(data, ensure_ascii=False) + "\n")
        runs = [dict(row) for row in conn.execute("SELECT * FROM agent_runs ORDER BY started_at")]
        cases = snapshot["cases"]
        summary = audit_summary(conn, snapshot)
        intake_payloads = [
            dict(row)
            for row in conn.execute(
                "SELECT 'case' AS entity_type,id,payload_path,payload_sha256,payload_size_bytes FROM cases WHERE payload_path IS NOT NULL "
                "UNION ALL SELECT 'signal',id,payload_path,payload_sha256,payload_size_bytes FROM case_signals WHERE payload_path IS NOT NULL"
            )
        ]
    finally:
        conn.close()

    (stage / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "cases.json").write_text(
        json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "agent-runs.json").write_text(
        json.dumps(runs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (stage / "health.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    shutil.copy2(root / "views" / "BOARD.md", stage / "BOARD.md")
    source_db = connect(root)
    audit_db = sqlite3.connect(str(stage / "state.sqlite3"))
    try:
        source_db.backup(audit_db)
    finally:
        audit_db.close()
        source_db.close()
    package_root = PACKAGE_ROOT
    if (package_root / "guidance").exists():
        shutil.copytree(package_root / "guidance", stage / "guidance")
    for name in ("prompts", "runs", "outbox"):
        if (source_root / name).exists():
            shutil.copytree(
                source_root / name, stage / name, ignore=shutil.ignore_patterns("*.lock")
            )
    # A crash or an outer caller's rollback may leave an unregistered snapshot.
    # Only payloads referenced by this database snapshot belong in its audit.
    intake_copied, intake_skipped = [], []
    for payload in intake_payloads:
        identity = {"id": payload["id"], "entity_type": payload["entity_type"]}
        path = Path(payload["payload_path"])
        try:
            relative = path.resolve().relative_to((source_root / "intake").resolve())
        except ValueError:
            intake_skipped.append(identity | {"reason": "payload is outside the intake directory"})
            continue
        if not path.is_file():
            intake_skipped.append(identity | {"reason": "payload file is missing"})
            continue
        target = stage / "intake" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if hash_file(target) != (payload["payload_sha256"], payload["payload_size_bytes"]):
            target.unlink()
            intake_skipped.append(identity | {"reason": "payload changed since intake"})
        else:
            intake_copied.append(identity | {"archive_path": str(target.relative_to(stage))})
    (stage / "intake-export.json").write_text(
        json.dumps({"copied": intake_copied, "skipped": intake_skipped}, indent=2) + "\n",
        encoding="utf-8",
    )
    audit_guide = textwrap.dedent(
        """\
        # How to review this swarm run

        Start with `snapshot.json`, `health.json`, and `BOARD.md`. For a persistent service,
        use `cases.json` for complete case and signal histories. Check `intake-export.json`
        and `artifact-export.json` for files omitted because they changed or disappeared.
        Archive integrity verification does not prove that every source file was available.
        Use `events.jsonl` to
        reconstruct causality and `agent-runs.json` plus `runs/` to inspect individual
        invocations. The SQLite database is included for custom queries.

        Review for: stale facts, weak or unstable workstreams, forecast misses, speculative
        tasks, duplicated work, missing checkpoints,
        long human-decision propagation, expired leases, weak verification, manager churn,
        excessive fan-out, policy stages that were skipped or claimed by disallowed agent
        identities, named skills without evidence, duplicate inbound cases or signals,
        missed follow-ups, untriaged material findings, finding-to-work linkage, overdue or
        repeatedly rescheduled external waits, duplicate wake signals, manager-review latency,
        failed or duplicated external deliveries, missing provider receipts, and work that
        bypassed canonical state.

        Secrets warning: prompts, stdout, stderr, and registered artifacts may contain
        sensitive material. Inspect this archive before sharing it outside your organization.
        """
    )
    (stage / "REVIEW_ME.md").write_text(audit_guide, encoding="utf-8")
    copied = []
    skipped = []
    if include_artifacts:
        artifact_dir = stage / "artifacts"
        artifact_dir.mkdir()
        limit = max_artifact_mb * 1024 * 1024
        for artifact in snapshot["artifacts"]:
            path = Path(artifact["path"])
            if path.is_file() and path.stat().st_size <= limit:
                target = artifact_dir / (artifact["id"] + "-" + path.name)
                shutil.copy2(path, target)
                if hash_file(target)[0] != artifact["sha256"]:
                    target.unlink()
                    skipped.append(
                        {"id": artifact["id"], "reason": "content changed since registration"}
                    )
                else:
                    copied.append(
                        {"id": artifact["id"], "archive_path": str(target.relative_to(stage))}
                    )
            else:
                skipped.append(
                    {
                        "id": artifact["id"],
                        "path": str(path),
                        "reason": "missing, non-file, or over size limit",
                    }
                )
    (stage / "artifact-export.json").write_text(
        json.dumps({"copied": copied, "skipped": skipped}, indent=2) + "\n", encoding="utf-8"
    )


def verify_audit(path):
    """Check manifest structure and streaming content hashes without extracting files."""
    problems = []
    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open("swarm-audit/manifest.json") as handle:
                raw = handle.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("Audit manifest exceeds 16 MiB")
            manifest = json.loads(raw)
            if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
                raise ValueError("Unsupported audit manifest format")
            if not isinstance(manifest.get("files"), list):
                raise ValueError("Audit manifest files must be an array")
            expected = {"swarm-audit/manifest.json"}
            for item in manifest["files"]:
                if not isinstance(item, dict):
                    raise ValueError("Audit manifest file entries must be objects")
                relative = item.get("path")
                size = item.get("size_bytes")
                sha = item.get("sha256")
                if (
                    not isinstance(relative, str)
                    or not relative
                    or "\\" in relative
                    or any(part in {"", ".", ".."} for part in relative.split("/"))
                ):
                    raise ValueError("Audit manifest contains an invalid relative path")
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    raise ValueError("Audit file size must be a non-negative integer")
                if (
                    not isinstance(sha, str)
                    or len(sha) != 64
                    or any(c not in "0123456789abcdef" for c in sha)
                ):
                    raise ValueError("Audit file digest must be a SHA-256 hex string")
                name = "swarm-audit/" + relative
                if name in expected:
                    raise ValueError("Duplicate manifest path: " + name)
                expected.add(name)
                try:
                    info = archive.getinfo(name)
                    if info.file_size != size:
                        problems.append("Integrity mismatch: " + name)
                        continue
                    digest = hashlib.sha256()
                    with archive.open(info) as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != sha:
                        problems.append("Integrity mismatch: " + name)
                except KeyError:
                    problems.append("Missing " + name)
            names = archive.namelist()
            if len(names) != len(set(names)):
                problems.append("Duplicate archive entries")
            if set(names) != expected:
                problems.append("Archive contains unmanifested or missing entries")
    except (OSError, KeyError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        problems.append(str(exc))
    return {"ok": not problems, "problems": problems}


def structural_telemetry(conn):
    """Read only allowlisted counters, never free text, paths, or payloads."""
    state = runtime_state(conn)
    return {
        "event_watermark": conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0],
        "desired_state": state["desired_state"],
        "outcome": state["outcome"],
        "task_counts": dict(conn.execute("SELECT status,COUNT(*) FROM tasks GROUP BY status")),
        "attempt_counts": dict(conn.execute("SELECT state,COUNT(*) FROM attempts GROUP BY state")),
    }


def export_audit(root, output, include_artifacts=False, max_artifact_mb=25, share_safe=False):
    """Publish one consistent export, keeping the old output intact on failure."""
    if max_artifact_mb < 0:
        raise SwarmError("Artifact size limit must not be negative")
    output = Path(output).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if output == root or root in output.parents:
        raise SwarmError("Write audit exports outside the mission state directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Stage on the output filesystem so publication is an atomic rename.
    with tempfile.TemporaryDirectory(prefix=".swarm-export-", dir=str(output.parent)) as temp:
        directory = Path(temp)
        stage = directory / "swarm-audit"
        stage.mkdir()
        manifest = {
            "format_version": 1,
            "created_at": utcnow(),
            "swarmctl_version": VERSION,
            "include_artifacts": bool(include_artifacts and not share_safe),
            "privacy_mode": "structural-only" if share_safe else "private-full",
        }
        if share_safe:
            conn = connect(root)
            try:
                conn.execute("BEGIN")
                telemetry = structural_telemetry(conn)
            finally:
                conn.close()
            (stage / "telemetry.json").write_text(
                json.dumps(telemetry, indent=2) + "\n", encoding="utf-8"
            )
            manifest["event_watermark"] = telemetry["event_watermark"]
        else:
            # Freeze SQLite once, and do not reconcile this historical copy.
            frozen = directory / "workspace"
            frozen.mkdir()
            source = connect(root)
            target = sqlite3.connect(str(frozen / "state.sqlite3"))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            stage_private_audit(frozen, root, stage, include_artifacts, max_artifact_mb)
            conn = connect(frozen)
            try:
                explanation = explain_state(conn)
            finally:
                conn.close()
            (stage / "explanation.json").write_text(
                json.dumps(explanation, indent=2) + "\n", encoding="utf-8"
            )
            manifest["source_root"] = str(root)
            manifest["event_watermark"] = explanation["event_watermark"]
        files = []
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                sha, size = hash_file(path)
                files.append(
                    {"path": str(path.relative_to(stage)), "sha256": sha, "size_bytes": size}
                )
        manifest["files"] = files
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        archive_path = directory / "complete.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, str(path.relative_to(directory)))
        os.replace(str(archive_path), str(output))
    return output
