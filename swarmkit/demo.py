"""A synthetic pipeline recovery demonstrating durable work without a harness."""

import datetime as dt

from .audit import export_audit
from .core import SwarmError
from .decisions import acknowledge_decision, resolve_decision
from .setup import initialize
from .storage import connect
from .tasks import (
    add_task,
    add_workstream,
    block_task,
    checkpoint_task,
    claim_task,
    complete_mission,
    complete_task,
    record_fact,
    set_mission_phase,
    update_workstream,
)
from .views import render_board, render_status_report


def run_demo(root, output):
    """Create a new isolated example; never invoke a harness or an external tool."""
    if output.exists():
        raise SwarmError("Demo output already exists: %s" % output)
    initialize(
        root,
        "Restore correct delivery through a synthetic pipeline",
        ["New records reach the destination", "Backlog is accounted for"],
        ["Require approval before pausing ingestion"],
    )
    conn = connect(root)
    try:
        diagnosis_stream = add_workstream(
            conn,
            "Diagnose the failure",
            "Identify the first failing boundary with evidence",
            "manager",
            "ACTIVE",
        )
        repair_stream = add_workstream(
            conn,
            "Restore delivery",
            "Restore correct live delivery and account for backlog",
            "manager",
            "PLANNED",
        )
        discovery = add_task(
            conn,
            "Trace a representative record",
            "Identify the first pipeline boundary that rejects the record.",
            "discovery",
            ["Evidence identifies the last successful and first failing boundary"],
            [],
            90,
            "manager",
            True,
            diagnosis_stream,
        )
        repair = add_task(
            conn,
            "Repair the supported failure",
            "Apply and verify the smallest repair supported by discovery evidence.",
            "implementation",
            ["A representative record reaches the destination"],
            [discovery],
            80,
            "manager",
            True,
            repair_stream,
        )
        claim_task(conn, discovery, "worker-discovery", 1800)
        record_fact(
            conn,
            "destination-authentication",
            "writes rejected after credential rotation",
            "synthetic request trace req-demo at destination boundary",
            "worker-discovery",
            discovery,
            ttl_seconds=3600,
        )
        checkpoint_task(
            conn,
            discovery,
            "worker-discovery",
            "Destination rejection isolated",
            "Complete with trace evidence",
            1800,
        )
        evidence = root / "synthetic-trace.txt"
        evidence.write_text(
            "source=ok queue=ok destination=authentication-rejected\n", encoding="utf-8"
        )
        complete_task(
            conn,
            discovery,
            "worker-discovery",
            "Credential rotation broke destination writes",
            ["Synthetic trace reaches destination and receives authentication rejection"],
            [str(evidence)],
        )
        update_workstream(
            conn,
            diagnosis_stream,
            "manager",
            status="DONE",
            summary="Destination credential rejection isolated with a representative trace",
        )
        set_mission_phase(conn, "EXECUTION", "manager")
        forecast_latest = (
            (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        update_workstream(
            conn,
            repair_stream,
            "manager",
            status="ACTIVE",
            summary="Repair is ready for an approved controlled window",
            forecast_latest=forecast_latest,
            forecast_confidence="medium",
            forecast_basis="Synthetic repair and backlog validation remain",
        )
        claim_task(conn, repair, "worker-repair", 1800)
        decision = block_task(
            conn,
            repair,
            "worker-repair",
            "human_decision",
            "May ingestion pause for the controlled repair?",
            "Pause to reduce duplicate-replay risk",
            ["Pause", "Continue"],
        )
        resolve_decision(conn, decision, "Pause for the controlled repair", "human")
        claim_task(conn, repair, "worker-repair-2", 1800)
        acknowledge_decision(conn, decision, repair, "worker-repair-2")
        checkpoint_task(
            conn,
            repair,
            "worker-repair-2",
            "Applied decision and rotated credential",
            "Verify delivery and backlog",
            1800,
        )
        complete_task(
            conn,
            repair,
            "worker-repair-2",
            "Delivery restored and backlog drained",
            ["Synthetic live record arrived", "Synthetic backlog count reached zero"],
            [],
        )
        update_workstream(
            conn,
            repair_stream,
            "manager",
            status="DONE",
            summary="Delivery restored and synthetic backlog validation passed",
        )
        set_mission_phase(conn, "VERIFICATION", "manager")
        complete_mission(
            conn,
            "Live delivery and backlog success conditions verified in the synthetic fixture",
            "manager",
        )
    finally:
        conn.close()
    render_board(root)
    render_status_report(root)
    output = export_audit(root, output, include_artifacts=True)
    return output
