#!/usr/bin/env python3
"""Measure invocation cost with a long mission history, using a disposable fixture.

Pass --source to compare another Swarmkit checkout. Timings are observations, not
CI thresholds; regression tests enforce bounded reads independently of hardware.
"""

import argparse
import importlib
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc


def measure(operation, repeats):
    samples = []
    peak = 0
    for index in range(repeats):
        tracemalloc.start()
        started = time.perf_counter()
        operation(index)
        samples.append(time.perf_counter() - started)
        peak = max(peak, tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    return {"median_seconds": round(statistics.median(samples), 6), "peak_python_bytes": peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tasks", type=int, default=1000, help="Historical completed tasks")
    parser.add_argument("--events", type=int, default=25000, help="Historical events")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.tasks < 0 or args.events < 0 or args.repeats < 1:
        parser.error("Counts must be non-negative and repeats must be positive")
    sys.path.insert(0, str(args.source.resolve()))
    swarm = importlib.import_module("swarmctl")
    with tempfile.TemporaryDirectory(prefix="swarm-benchmark-") as temp:
        root = Path(temp) / ".swarm"
        mission = swarm.initialize(root, "Benchmark context retrieval", ["Bounded context"], [])
        conn = swarm.connect(root)
        try:
            target = swarm.add_task(
                conn,
                "Current work",
                "Inspect current evidence",
                "discovery",
                ["Checked"],
                [],
                50,
                "manager",
                True,
            )
            now = swarm.utcnow()
            # Direct inserts deliberately isolate read scaling from planner cost.
            conn.executemany(
                """INSERT INTO tasks(id,mission_id,title,description,kind,status,acceptance_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,'DONE','["Checked"]',?,?)""",
                (
                    (
                        "history-%s" % n,
                        mission,
                        "Earlier work",
                        "Historical detail " * 30,
                        "discovery",
                        now,
                        now,
                    )
                    for n in range(args.tasks)
                ),
            )
            conn.executemany(
                """INSERT INTO events(id,mission_id,entity_type,entity_id,event_type,actor,occurred_at,payload_json)
                   VALUES(?,?,'mission',?,'BENCHMARK_EVENT','fixture',?,?)""",
                (
                    (
                        "history-event-%s" % n,
                        mission,
                        mission,
                        now,
                        json.dumps({"note": "Historical evidence " * 20}),
                    )
                    for n in range(args.events)
                ),
            )
            conn.commit()
            results = {
                "version": swarm.VERSION,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "fixture": {
                    "completed_tasks": args.tasks,
                    "historical_events": args.events,
                    "repeats": args.repeats,
                },
                "worker_prompt": measure(
                    lambda n: swarm.build_prompt(root, "worker", "benchmark-worker", target),
                    args.repeats,
                ),
                "manager_prompt": measure(
                    lambda n: swarm.build_prompt(root, "manager", "benchmark-manager"), args.repeats
                ),
                "leased_inbox_50": measure(
                    lambda n: swarm.lease_inbox(conn, "benchmark-inbox-%s" % n, limit=50),
                    args.repeats,
                ),
            }
        finally:
            conn.close()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
