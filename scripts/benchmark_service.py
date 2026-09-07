#!/usr/bin/env python3
"""Measure reconciliation with many active cases; disposable, provider-free fixtures."""

import argparse
import importlib
import json
from pathlib import Path
import platform
import sys
import tempfile

from benchmark_context import measure


def active_case_fixture(swarm, root, count):
    mission = swarm.initialize(
        root, "Active service benchmark", ["Cases remain responsive"], [], "SERVICE"
    )
    conn = swarm.connect(root)
    now = swarm.utcnow()
    for n in range(count):
        stream, case = "stream-%s" % n, "case-%s" % n
        conn.execute(
            "INSERT INTO workstreams(id,mission_id,name,outcome,status,created_at,updated_at) VALUES(?,?,?,?,'ACTIVE',?,?)",
            (stream, mission, "Investigate", "Verified result", now, now),
        )
        conn.execute(
            "INSERT INTO cases(id,mission_id,source,external_id,title,objective,status,workstream_id,metadata_json,request_fingerprint,created_by,created_at,updated_at) "
            "VALUES(?,?,'fixture',?,? ,?,'ACTIVE',?,'{}',?,'fixture',?,?)",
            (case, mission, case, "Case", "Verify outcome", stream, case, now, now),
        )
        for stage in range(5):
            task = "task-%s-%s" % (n, stage)
            status = "DONE" if stage < 2 else "READY" if stage == 2 else "PROPOSED"
            conn.execute(
                "INSERT INTO tasks(id,mission_id,title,description,kind,status,authorized,acceptance_json,result,created_at,updated_at) VALUES(?,?,?,?,'discovery',?,1,'[\"Verified\"]',?,?,?)",
                (
                    task,
                    mission,
                    "Task",
                    "Inspect evidence",
                    status,
                    "Recorded evidence " * 400 if status == "DONE" else None,
                    now,
                    now,
                ),
            )
            conn.execute("INSERT INTO case_tasks VALUES(?,?)", (case, task))
            conn.execute("INSERT INTO task_workstreams VALUES(?,?)", (task, stream))
            if stage > 2:
                conn.execute("INSERT INTO task_dependencies VALUES(?,?)", (task, "task-%s-2" % n))
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cases", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--review-triggers", type=int, default=1000)
    args = parser.parse_args()
    if args.cases < 1 or args.repeats < 1 or args.review_triggers < 1:
        parser.error("Counts must be positive")
    sys.path.insert(0, str(args.source.resolve()))
    swarm = importlib.import_module("swarmctl")
    with tempfile.TemporaryDirectory(prefix="swarm-service-benchmark-") as temp:
        conn = active_case_fixture(swarm, Path(temp) / ".swarm", args.cases)
        try:
            reads = []
            conn.set_trace_callback(
                lambda sql: (
                    reads.append(sql)
                    if sql.lstrip().upper().startswith(("SELECT", "WITH"))
                    else None
                )
            )
            swarm.reconcile_conn(conn)
            conn.set_trace_callback(None)
            result = {
                "version": swarm.VERSION,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cases": args.cases,
                "tasks": args.cases * 5,
                "reconcile_read_statements": len(reads),
                "case_reconciliation": measure(lambda _: swarm.reconcile_cases(conn), args.repeats),
                "full_reconciliation": measure(lambda _: swarm.reconcile_conn(conn), args.repeats),
            }

            def review_burst(_):
                # Measure the same burst each time, excluding fixture growth and
                # fsync differences. All events/index rows roll back afterward.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for n in range(args.review_triggers):
                        swarm.request_manager_review(conn, "task completed", "task", "burst-%s" % n)
                finally:
                    conn.rollback()

            result["review_triggers"] = args.review_triggers
            result["review_burst"] = measure(review_burst, args.repeats)
            # Keep the health workload valid and avoid measuring thousands of
            # deliberately absent fixture summaries as reported problems.
            conn.execute("UPDATE tasks SET verification_json='[\"Verified\"]',title=id")
            conn.execute("UPDATE workstreams SET progress_summary='Investigation in progress'")
            conn.commit()
            reads.clear()
            conn.set_trace_callback(
                lambda sql: (
                    reads.append(sql)
                    if sql.lstrip().upper().startswith(("SELECT", "WITH"))
                    else None
                )
            )
            swarm.doctor(conn)
            conn.set_trace_callback(None)
            result["health_read_statements"] = len(reads)
            result["health_check"] = measure(lambda _: swarm.doctor(conn), args.repeats)
        finally:
            conn.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
