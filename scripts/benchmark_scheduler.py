#!/usr/bin/env python3
"""Compare scheduling overhead with synthetic committed tasks and slow reviews.

Uses temporary missions and simulated dispatch; never invokes a model or provider.
Run the same script with --source pointing at two checkouts to compare behavior.
"""

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from unittest import mock


def measure(source, count, parallel, review_seconds, worker_seconds):
    sys.path.insert(0, str(source))
    import swarmctl as s
    from swarmkit import runtime

    with tempfile.TemporaryDirectory(prefix="swarm-scheduler-benchmark-") as directory:
        root = Path(directory) / ".swarm"
        s.initialize(root, "Benchmark committed work", ["All tasks checked"], [])
        conn = s.connect(root)
        for index in range(count):
            s.add_task(
                conn,
                str(index),
                "Synthetic work",
                "discovery",
                ["Checked"],
                [],
                50,
                "planner",
                True,
            )
        conn.close()
        path = root / "runner.json"
        config = json.loads(path.read_text())
        config.update(
            command=[sys.executable, "-c", "pass"],
            max_parallel=parallel,
            manager_review_debounce_seconds=0,
            scheduler_poll_seconds=0.002,
        )
        path.write_text(json.dumps(config))
        records = []
        lock = threading.Lock()
        start = time.monotonic()

        def dispatch(root, role, agent, task_id=None, dry_run=False):
            began = time.monotonic()
            time.sleep(review_seconds if role == "manager" else worker_seconds)
            conn = s.connect(root)
            try:
                if role != "manager":
                    s.complete_task(conn, task_id, agent, "Checked", ["Checked"], [])
            finally:
                conn.close()
            with lock:
                records.append((role, began - start, time.monotonic() - began))
            return {"exit_code": 0}

        with mock.patch.object(runtime, "dispatch", side_effect=dispatch):
            result = s.run_loop(root, 1000)
        elapsed = time.monotonic() - start
        workers = [item for item in records if item[0] != "manager"]
        return {
            "version": s.VERSION,
            "state": result["state"],
            "tasks": len(workers),
            "elapsed_seconds": round(elapsed, 4),
            "manager_reviews": len(records) - len(workers),
            "mean_ready_to_dispatch_seconds": round(
                statistics.mean(item[1] for item in workers), 4
            ),
            "worker_slot_utilization": round(
                sum(item[2] for item in workers) / (parallel * elapsed), 4
            ),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tasks", type=int, default=12)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--review-seconds", type=float, default=0.06)
    parser.add_argument("--worker-seconds", type=float, default=0.04)
    args = parser.parse_args()
    if args.tasks < 1 or args.parallel < 1 or min(args.review_seconds, args.worker_seconds) <= 0:
        parser.error("Task counts, capacity and durations must be positive")
    print(
        json.dumps(
            measure(
                args.source.resolve(),
                args.tasks,
                args.parallel,
                args.review_seconds,
                args.worker_seconds,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
