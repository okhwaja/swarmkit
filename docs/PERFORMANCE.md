# Measuring long-history overhead

Swarmkit should spend its time doing useful work, rather than loading unrelated
mission history before every invocation. Context generation and inbox leases now
limit SQL rows before decoding JSON. Full snapshots, reports, entity histories,
and private audit exports intentionally return more complete information.

## Reproduce the measurement

The standard-library benchmark builds a disposable database. It does not invoke
an agent, modify a source checkout, or call external services:

```sh
python3 -B scripts/benchmark_context.py
python3 -B scripts/benchmark_context.py --source /path/to/older/swarmkit
python3 -B scripts/benchmark_context.py --tasks 10000 --events 250000
```

It measures worker prompts, manager prompts, and a 50-event leased inbox page.
Fixture setup is excluded. Each operation runs three times; the result records
median wall time and maximum Python allocation peak measured with `tracemalloc`.
Tracing adds overhead, and these are local observations rather than production
latency guarantees or flaky CI timing thresholds. Memory figures are Python
allocations, not total process RSS or SQLite's internal allocations.

## Observed results

Measured on 2026-09-07 UTC using Python 3.9.6 on macOS 26.6.2 arm64. The baseline
is commit `9587139` (0.7.1); the improved implementation was measured at `35b6319`
on the local 0.8.0 development branch. Both used the same benchmark fixture.

With **1,000 completed tasks and 25,000 historical events**:

| Operation | Baseline median | Improved median | Baseline peak | Improved peak |
|---|---:|---:|---:|---:|
| Worker prompt | 264.387 ms | 2.014 ms | 57.91 MB | 0.170 MB |
| Manager prompt | 267.902 ms | 2.076 ms | 57.91 MB | 0.184 MB |
| Inbox lease, 50 events | 216.369 ms | 0.982 ms | 54.89 MB | 0.200 MB |

With **10,000 completed tasks and 250,000 historical events**, the improved
implementation measured 2.172 ms for a worker prompt, 4.173 ms for a manager
prompt, and 0.955 ms for the inbox lease. Python allocation peaks stayed at
approximately 0.170 MB, 0.184 MB, and 0.200 MB respectively.

The larger fixture demonstrates the intended scaling for inactive history. It
does not model thousands of simultaneously active cases, large provider files,
slow disks, or live harness execution. Regression tests separately verify that
inbox paging happens before JSON decoding and worker prompts do not load the
full mission snapshot.
