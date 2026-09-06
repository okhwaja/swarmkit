#!/usr/bin/env python3
"""Create a complete synthetic run and audit ZIP without invoking an AI harness."""

import argparse
import datetime as dt
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

import swarmctl  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="New .swarm directory")
    parser.add_argument("--output", required=True, help="Audit ZIP to create")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    swarmctl.initialize(
        root,
        "Restore correct delivery through a synthetic pipeline",
        ["New records reach the destination", "Backlog is accounted for"],
        ["Require approval before pausing ingestion"],
    )
    conn = swarmctl.connect(root)
    try:
        diagnosis_stream = swarmctl.add_workstream(
            conn, "Diagnose the failure", "Identify the first failing boundary with evidence",
            "manager", "ACTIVE",
        )
        repair_stream = swarmctl.add_workstream(
            conn, "Restore delivery", "Restore correct live delivery and account for backlog",
            "manager", "PLANNED",
        )
        discovery = swarmctl.add_task(
            conn,
            "Trace a representative record",
            "Identify the first pipeline boundary that rejects the record.",
            "discovery",
            ["Evidence identifies the last successful and first failing boundary"],
            [], 90, "manager", True, diagnosis_stream,
        )
        repair = swarmctl.add_task(
            conn,
            "Repair the supported failure",
            "Apply and verify the smallest repair supported by discovery evidence.",
            "implementation",
            ["A representative record reaches the destination"],
            [discovery], 80, "manager", True, repair_stream,
        )
        swarmctl.claim_task(conn, discovery, "worker-discovery", 1800)
        swarmctl.record_fact(
            conn, "destination-authentication", "writes rejected after credential rotation",
            "synthetic request trace req-demo at destination boundary", "worker-discovery",
            discovery, ttl_seconds=3600,
        )
        swarmctl.checkpoint_task(
            conn, discovery, "worker-discovery", "Destination rejection isolated",
            "Complete with trace evidence", 1800,
        )
        evidence = root / "synthetic-trace.txt"
        evidence.write_text("source=ok queue=ok destination=authentication-rejected\n", encoding="utf-8")
        swarmctl.complete_task(
            conn, discovery, "worker-discovery", "Credential rotation broke destination writes",
            ["Synthetic trace reaches destination and receives authentication rejection"],
            [str(evidence)],
        )
        swarmctl.update_workstream(
            conn, diagnosis_stream, "manager", status="DONE",
            summary="Destination credential rejection isolated with a representative trace",
        )
        swarmctl.set_mission_phase(conn, "EXECUTION", "manager")
        forecast_latest = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        swarmctl.update_workstream(
            conn, repair_stream, "manager", status="ACTIVE",
            summary="Repair is ready for an approved controlled window",
            forecast_latest=forecast_latest, forecast_confidence="medium",
            forecast_basis="Synthetic repair and backlog validation remain",
        )
        swarmctl.claim_task(conn, repair, "worker-repair", 1800)
        decision = swarmctl.block_task(
            conn, repair, "worker-repair", "human_decision",
            "May ingestion pause for the controlled repair?",
            "Pause to reduce duplicate-replay risk", ["Pause", "Continue"],
        )
        swarmctl.resolve_decision(conn, decision, "Pause for the controlled repair", "human")
        swarmctl.claim_task(conn, repair, "worker-repair-2", 1800)
        swarmctl.acknowledge_decision(conn, decision, repair, "worker-repair-2")
        swarmctl.checkpoint_task(
            conn, repair, "worker-repair-2", "Applied decision and rotated credential",
            "Verify delivery and backlog", 1800,
        )
        swarmctl.complete_task(
            conn, repair, "worker-repair-2", "Delivery restored and backlog drained",
            ["Synthetic live record arrived", "Synthetic backlog count reached zero"], [],
        )
        swarmctl.update_workstream(
            conn, repair_stream, "manager", status="DONE",
            summary="Delivery restored and synthetic backlog validation passed",
        )
        swarmctl.set_mission_phase(conn, "VERIFICATION", "manager")
        swarmctl.complete_mission(
            conn, "Live delivery and backlog success conditions verified in the synthetic fixture",
            "manager",
        )
    finally:
        conn.close()
    swarmctl.render_board(root)
    swarmctl.render_status_report(root)
    output = swarmctl.export_audit(root, Path(args.output), include_artifacts=True)
    print(output)


if __name__ == "__main__":
    main()
