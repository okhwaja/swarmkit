# Local improvement work log

Started: 2026-09-07 04:17:44 UTC. Allowance ends: 2026-09-07 16:17:44 UTC.
Branch: `codex/readable-reliable-swarmkit`. Do not push, open a PR, or merge remotely.
Baseline: main at 9587139, Swarmkit 0.7.1/schema 8, 71 tests, 6,839-line CLI/engine.

## Intended work

1. Reproduce lifecycle, transaction, restart, completion, and service-intake holes.
2. Fix invariants with focused regression tests and an explicit transaction boundary.
3. Separate storage/domain/runtime/presentation/CLI responsibilities into ordinary
   modules; preserve command compatibility without frameworks or dynamic dispatch.
4. Bound prompt/inbox reads at the database, measure scale, and add regression checks.
5. Make the first-use path obvious: fit, examples, a safe demo, setup, run, inspect,
   wait/answer/resume, and honest operating limits. Reduce documentation duplication.
6. Exercise the expected performance, incident, review, port, and restart journeys;
   improve primitive gaps rather than hard-coding a provider or workflow.
7. Strengthen contributor guidance, packaging, and local release checks.
8. Leave a full newcomer-friendly report with motivations, implementation,
   evidence, limitations, and local commit navigation.

## Observations to investigate (not yet confirmed)

- Atomic decorators coexist with helpers that commit or begin transactions internally.
- Case creation and policy/task attachment occur in separate commits.
- Prompts materialize entire mission/case/event histories before truncation.
- A reported DONE result may mask cancellation/partial work or stale decisions.
- Recovery, manager-review completion, and pause/drain differ between manual and runner paths.
- Checkout registration needs actual workspace context passed to agents, not just cwd.
- CLI and README expose too much protocol before showing a simple useful first run.

## Validation and progress

- Baseline release check started; results in /tmp/swarmkit-improvement-baseline.log.
- Documentation impact: CLI/state, user journey, harness, setup, architecture,
  role behavior, migrations/release metadata.

- Baseline release check passed: 71 tests in both source and extracted package.
- Reproduced six transaction/lifecycle failures. Domain operations now share one
  atomic boundary, using savepoints under an existing transaction. Failed case
  planning and failed signal wakeups leave no partial database state. Cancelled
  cases reject task links, policy application, and wakeups.
- Split the engine into explicit modules with no import cycles, keeping existing
  commands and root Python compatibility imports. Added `python3 -m swarmkit`.
- Temporary formatter installed only under /tmp; no runtime dependency added.
- Added `docs/CODE_MAP.md` to explain module ownership and transaction rules.

- Saved local commit 05cb4cc for transaction fixes/module split. Release checks
  passed 77 tests in source and extracted package. Nothing pushed.
- Inbox reads now page within SQL. A 5,003-event regression workload decoded only
  7 events for a 7-event lease. Scope expansion uses a CTE, not a Python list of
  bound IDs. Plain reads honor --limit; legacy advancement uses scoped offsets.
- Prompts no longer build full mission snapshots for each worker. Added bounded
  context pages, newest-first case signals, checkout/evidence/runtime context, and
  progressive size reduction that retains the primary task and mission.
- Added schema 9 indexes for context/event relations. No history is discarded.
- Lease timestamps now use the same sortable UTC format; nonpositive renewals
  are rejected. Transaction commit failures also roll back pending writes.
- Current focused/full source checks: 91 tests passing. Broader release validation
  will repeat after the next feature group.

- Saved local commit 9a6bff5 for bounded inbox/context reads; release check passed
  91 tests in source and extracted package.
- Reproduced and fixed five decision-fencing gaps: nonowners could acknowledge;
  a new attempt inherited an old agent's acknowledgement; revised/newly linked
  decisions left old attempts RUNNING; revisions left obsolete waits active;
  executing effects were not made uncertain on decision change. All 96 tests pass.
- Upcoming journey audit findings: mixed cancelled/completed case tasks can be
  labeled DONE without a partial outcome; auto-cancelled intake conflicts with
  applying a replacement policy; delivery subprocesses need the same liveness
  and uncertain-result handling as ordinary harness runs. These are not fixed yet.

- Saved local commit 59885ff for decision attempt fencing (96 passing source tests).
- Reproduced delivery clean-exit replay, lease-expiry replay, timeout byte/string
  logging failure, and controller-crash liveness omission. Implemented UNKNOWN
  delivery state, provider reconciliation command, shared streaming process helper,
  inherited delivery process locks, delivery recovery, and unique delivery prompts.
- Final reports can be sent after finite task completion, while pause/cancel still
  stops new delivery claims. Existing ambiguous delivery error markers upgrade to
  UNKNOWN in schema 9. Added provider-reconciliation and upgrade tests.
- Ran temporary Ruff static checks; removed unused imports from the module split.
  Runtime remains standard-library only. Source suite passed 103 before the last
  migration regression was added; full validation follows.
