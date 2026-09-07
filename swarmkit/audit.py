"""Export and verify portable mission audit bundles."""

from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import tempfile
import textwrap
import zipfile

from .core import PACKAGE_ROOT, CLI_PATH, VERSION, hash_file, json_load, parse_time, utcnow
from .diagnostics import doctor
from .queries import case_dict, explain_state, mission_snapshot
from .storage import connect
from .views import render_board


def audit_summary(conn):
    snap = mission_snapshot(conn)
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


def _export_audit(root, output, include_artifacts=False, max_artifact_mb=25):
    render_board(root)
    conn = connect(root)
    try:
        snapshot = mission_snapshot(conn)
        events = []
        for row in conn.execute("SELECT * FROM events ORDER BY seq"):
            data = dict(row)
            data["payload"] = json_load(data.pop("payload_json"), {})
            events.append(data)
        runs = [dict(row) for row in conn.execute("SELECT * FROM agent_runs ORDER BY started_at")]
        cases = [
            case_dict(conn, row)
            for row in conn.execute("SELECT * FROM cases ORDER BY created_at, id")
        ]
        summary = audit_summary(conn)
    finally:
        conn.close()

    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": 1,
        "created_at": utcnow(),
        "swarmctl_version": VERSION,
        "source_root": str(root),
        "include_artifacts": bool(include_artifacts),
    }
    with tempfile.TemporaryDirectory(prefix="swarm-audit-") as tmp:
        stage = Path(tmp) / "swarm-audit"
        stage.mkdir()
        (stage / "snapshot.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (stage / "cases.json").write_text(
            json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (stage / "events.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8"
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
        if (root / "prompts").exists():
            shutil.copytree(root / "prompts", stage / "prompts")
        if (root / "runs").exists():
            shutil.copytree(root / "runs", stage / "runs")
        if (root / "outbox").exists():
            shutil.copytree(root / "outbox", stage / "outbox")
        if (root / "intake").exists():
            shutil.copytree(root / "intake", stage / "intake")
        audit_guide = textwrap.dedent(
            """\
            # How to review this swarm run

            Start with `snapshot.json`, `health.json`, and `BOARD.md`. For a persistent service,
            use `cases.json` for complete case and signal histories. Use `events.jsonl` to
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
        with zipfile.ZipFile(str(output), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(str(path), str(path.relative_to(stage.parent)))
    return output


def verify_audit(path):
    problems = []
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("swarm-audit/manifest.json"))
            expected = {"swarm-audit/manifest.json"}
            for item in manifest["files"]:
                name = "swarm-audit/" + item["path"]
                expected.add(name)
                try:
                    data = archive.read(name)
                except KeyError:
                    problems.append("Missing " + name)
                    continue
                if (
                    len(data) != item["size_bytes"]
                    or hashlib.sha256(data).hexdigest() != item["sha256"]
                ):
                    problems.append("Integrity mismatch: " + name)
            names = archive.namelist()
            if len(names) != len(set(names)):
                problems.append("Duplicate archive entries")
            if set(names) != expected:
                problems.append("Archive contains unmanifested or missing entries")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        problems.append(str(exc))
    return {"ok": not problems, "problems": problems}


def export_audit(root, output, include_artifacts=False, max_artifact_mb=25, share_safe=False):
    # Freeze SQLite once. All derived files are computed from this same snapshot.
    with tempfile.TemporaryDirectory(prefix="swarm-snapshot-") as temp:
        frozen = Path(temp) / "workspace"
        frozen.mkdir()
        source = connect(root)
        target = sqlite3.connect(str(frozen / "state.sqlite3"))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        for name in ("prompts", "runs", "outbox", "intake"):
            if (root / name).exists():
                shutil.copytree(root / name, frozen / name, ignore=shutil.ignore_patterns("*.lock"))
        result = _export_audit(frozen, output, include_artifacts, max_artifact_mb)
        # Add deterministic attempt-level diagnostics from the same frozen DB.
        conn = connect(frozen)
        try:
            explanation = explain_state(conn)
        finally:
            conn.close()
        with zipfile.ZipFile(result) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(contents.pop("swarm-audit/manifest.json"))
        manifest["source_root"] = str(root)
        manifest["event_watermark"] = explanation["event_watermark"]
        if share_safe:
            # Allowlist structural telemetry. Free text, paths, prompts, payloads,
            # receipts, and SQLite are deliberately excluded, not regex-redacted.
            safe = {
                "event_watermark": explanation["event_watermark"],
                "desired_state": explanation["runtime"]["desired_state"],
                "outcome": explanation["runtime"]["outcome"],
                "task_counts": {},
                "attempt_counts": {},
            }
            for task in explanation["tasks"]:
                safe["task_counts"][task["status"]] = safe["task_counts"].get(task["status"], 0) + 1
            for attempt in explanation["attempts"]:
                safe["attempt_counts"][attempt["state"]] = (
                    safe["attempt_counts"].get(attempt["state"], 0) + 1
                )
            contents = {"swarm-audit/telemetry.json": (json.dumps(safe, indent=2) + "\n").encode()}
            manifest.pop("source_root", None)
        else:
            contents["swarm-audit/explanation.json"] = (
                json.dumps(explanation, indent=2) + "\n"
            ).encode()
        manifest["privacy_mode"] = "structural-only" if share_safe else "private-full"
        manifest["files"] = [
            {
                "path": name.removeprefix("swarm-audit/"),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
            for name, data in sorted(contents.items())
        ]
        contents["swarm-audit/manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(contents.items()):
                archive.writestr(name, data)
        return result
