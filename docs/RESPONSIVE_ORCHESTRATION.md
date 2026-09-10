# Responsive orchestration

Swarmkit coordinates evolving work through durable events instead of rigid
worker waves. The bounded run loop can review a meaningful result while
unrelated work is still active, and it can assign newly justified work whenever
a harness-process slot becomes free.

This document is authoritative for manager-review triggers, elevated findings,
external waits, wakeups, and responsive scheduling.
It realizes the behavior and acceptance scenarios in the preserved
[responsive-orchestration product spec](RESPONSIVE_ORCHESTRATION_PRODUCT_SPEC.md).

## Execution model

`run --max-cycles N` is a bounded event loop. A cycle is a scheduling turn that
launches either:

- one serialized manager review; or
- a batch of ready workers up to the remaining `max_parallel` capacity.

The loop polls canonical state every `scheduler_poll_seconds` while harness
processes are alive. A completed task, material or urgent finding, expired
lease, task entering external wait, or missed wait deadline creates a durable
manager-review trigger. Normal triggers coalesce for
`manager_review_debounce_seconds`; urgent triggers are immediately eligible.
Each newly created review contains at most 50 triggers. Larger bursts create
additional serialized batches. Identity lookups deduplicate a trigger across all
pending batches, including earlier full batches. A repeated trigger marked urgent
promotes its existing batch instead of creating a duplicate. A new observation
while that trigger's batch is running or finished can request another review.
Each batch still needs a disposition for every trigger in strict mode. Legacy
oversized batches retain their complete order after upgrade; they receive no
additional triggers.
Only one manager review can be `RUNNING` at a time.

Manager reviews take scheduling priority when eligible capacity becomes available.
Existing workers continue under their original ownership and lease, and free slots
can dispatch work from the committed plan while a review is running. Newly created
or newly approved tasks are staged until that review succeeds. Ordinary worker
checkpoints do not request manager review.

`max_parallel` counts live manager, worker, and delivery processes. Claims for
agent and delivery dispatch enforce the shared limit in a write transaction.
Long-lived active processes therefore continue to consume capacity. Swarmkit
does not claim that a database transition stops a harness process or external
side effect.

Example runner controls:

```json
{
  "max_parallel": 3,
  "timeout_seconds": 3600,
  "scheduler_poll_seconds": 1,
  "manager_review_debounce_seconds": 1
}
```

The polling interval is the maximum expected detection delay while this
bounded run owns active processes. Swarmkit does not remain alive merely to
wait for a future timestamp.

## Elevated findings

A finding is evidence discovered inside a worker's assigned task that may
matter beyond that task. Only the current task owner can raise one:

```bash
swarmctl --root /work/run/.swarm finding raise \
  --task T-ID \
  --agent worker-ID \
  --significance MATERIAL \
  --summary "Retries can produce duplicate destination records" \
  --evidence "log:event-1042" \
  --evidence "src/retry.py:88" \
  --impact "Replay may violate the no-duplication success condition" \
  --recommendation "Run one bounded replay-safety investigation"
```

Significance controls review timing, not authority:

| Significance | Behavior |
|---|---|
| `ROUTINE` | Visible in state and considered at the next normal review |
| `MATERIAL` | Requests a timely, debounced manager review |
| `URGENT` | Requests immediate manager review and appears under Needs attention |

A finding never creates tasks, workstreams, or authorization. If work is
unsafe, the worker must also use the existing blocker or safety-stop path.

The manager closes every material or urgent finding with one disposition:

```bash
swarmctl --root /work/run/.swarm finding disposition FND-ID \
  --status INCORPORATED \
  --rationale "The evidence affects replay correctness" \
  --task T-FOLLOWUP \
  --workstream WS-REPLAY \
  --actor manager
```

`DEFERRED` means relevant but not pursued now. `DISMISSED` means unsupported,
duplicate, or outside the mission. Every disposition requires a rationale.
Resulting tasks and workstreams are optional links, but should be supplied when
the plan changes. A finite mission cannot complete while a `MATERIAL` or
`URGENT` finding remains open.

## Durable external waits

Waiting on CI, an import, a pipeline, or another provider is task state—not a
human decision and not active agent work. The current owner records the wait:

```bash
swarmctl --root /work/run/.swarm task wait-external T-ID \
  --agent worker-ID \
  --condition "Pipeline job reaches a terminal state" \
  --external-ref "provider-job-123" \
  --next-check-at 2030-01-01T00:15:00Z \
  --signal-expected \
  --deadline 2030-01-01T04:00:00Z
```

The deadline is mandatory. At least one of `--next-check-at` or
`--signal-expected` is required. The next check must not be after the deadline.
This transition:

- moves the task to `WAITING_EXTERNAL`;
- clears its owner and lease;
- records the condition, correlation reference, schedule, and deadline;
- leaves dependencies unsatisfied; and
- requests manager review because capacity became available.

The worker should then exit. The dispatcher preserves `WAITING_EXTERNAL` even
if that invocation exits unsuccessfully. A still-live harness process counts
against capacity until it actually exits, and another owner cannot claim the
task while that run is alive.

### Scheduled and deadline wakeups

`reconcile` and `run` wake a wait when its next-check time or deadline arrives.
The task becomes eligible for a fresh invocation and its next action explicitly
requires verification. A deadline wake also requests urgent manager review and
appears under Needs attention.

If the provider is still running, the fresh worker records another bounded
wait. Every interval remains in history.

### External signals

A trusted integration records a callback with a provider-stable idempotency
key:

```bash
swarmctl --root /work/run/.swarm wait signal W-ID \
  --source pipeline-provider \
  --external-id callback-9001 \
  --note "Provider reports job completion" \
  --actor pipeline-webhook
```

Signals are durable and idempotent by mission, source, and external ID. The
first valid wake condition changes the wait from `WAITING` to `WOKEN` and makes
the task eligible once. Repeated or simultaneous callbacks are recorded or
deduplicated without producing another claimable task. Task claiming remains
atomic.

A callback, check time, or deadline means only “inspect the real system now.”
It is never stored as task verification or success.

## Bounded-run outcomes

When no process is active and nothing is ready, the run exits. If future waits
remain, the result state is `WAITING_EXTERNAL` and includes:

- active wait count and details;
- earliest scheduled check;
- earliest deadline;
- number expecting external signals; and
- deadline-wake attention count.

An external scheduler can invoke `run` at the earliest check. A webhook adapter
can call `wait signal` and then invoke another bounded run. Swarmkit is neither
a hosted webhook endpoint nor a long-term calendar scheduler.

## Recovery and audit

Findings, dispositions, review batches, waits, signals, and wake reasons live in
SQLite and emit ordered events. They survive process restarts and are included
in `status`, the board, executive reports, health checks, and audit exports.

Review `health.json` for manager-review latency, finding counts, wait duration,
and wake-reason counts. Use `events.jsonl` to trace a resulting task or
workstream back to `FINDING_RAISED` and `FINDING_DISPOSITIONED`, or a resumed
task back to `EXTERNAL_WAIT_STARTED`, a signal, and `EXTERNAL_WAIT_WOKEN`.

Schema upgrades are additive. Existing tasks retain their state, ownership,
leases, dependencies, decisions, policy applications, and audit history. New
tables begin empty, and existing runner configurations use one-second polling
and manager-review debounce defaults when the keys are absent.

## Runtime safety and recovery (0.7.0)

The [durable runtime contract](RUNTIME_SAFETY.md) documents `pause`, `drain`,
`resume`, `cancel`, `abandon`, `recover`, `why`, and `serve`, along with leased
inboxes, effect reconciliation, task worktrees, resource leases, evidence
contracts, amendments, limits, model escalation, and audit verification.
Use its examples for new integrations. The
[roadmap backlog](ROADMAP_BACKLOG.md) distinguishes shipped slices from remaining
engineering work and owner decisions. Permission enforcement stays with the
harness and tools. Runtime process locking requires a single POSIX host.

## Inspect complete review batches

`review list` returns the newest 50 review summaries, including trigger counts,
without loading every trigger payload. Filter with `--status` or `--agent`, use
`--limit` (1–500), and continue with `--before LAST_REVIEW_ID`.

`review show REVIEW_ID` returns every ordered trigger and any recorded semantic
commit. A manager prompt includes its current leased review ID even when other
context overflows; retrieve that review before committing if the prompt omitted
triggers. Running reviews take precedence over pending reviews in the prompt.
The old `review-commit` command remains the mutation interface.

## Plan publication

New tasks and approvals made while a manager review is running are recorded in
`staged_tasks`. Their task IDs, criteria, dependencies, and requested authorization
are durable, but they cannot become eligible or be claimed until publication.
This applies to ordinary tasks, policy stages, and case-signal follow-ups. Tasks
from the last committed plan continue to use the normal transactional claim
checks: current authorization, decisions, dependencies, budgets, attempt identity,
unfinished harnesses, effects, and workspace creation.

A successful review publishes its staged task authorizations and its completion
event in one transaction. Strict mode requires `review-commit` first. Creating or
newly authorizing another task after that commit invalidates it, so the manager
must commit again. The commit event records the staged task IDs. In legacy mode,
a successful manager exit is the publication boundary, consistent with its
existing non-strict review-completion contract. Prefer strict mode for unattended
work that needs semantic review receipts.

A failed or interrupted review leaves its tasks staged. Its next successful
attempt must inspect, adopt, or cancel that work before committing. `review show`
includes attempt history and staged task IDs; task context includes acceptance
revision and pending publication. Cancellation and decision invalidations take
effect immediately. No long-running SQLite transaction is held while a model
reasons, and task timestamps are not an authorization boundary.

Managers use a fresh identity for each attempt and must pass that identity in
`--actor` arguments. A known obsolete manager identity cannot create or approve
new plan authorizations. `review-commit` and completion are fenced to the current
lease owner. Permission to invoke commands remains a harness responsibility.

## Review retries and scheduling delays

Failure accounting is durable and independent of normal event batching. Configure
mission limits with `configure --limits`:

```json
{
  "max_manager_failures": 3,
  "review_backoff_seconds": 2,
  "review_backoff_cap_seconds": 300
}
```

These are the defaults. A failed exit, missing strict commit, expired review
lease, or proven abandoned manager closes one attempt and schedules a capped
exponential retry (2, 4, 8, ... seconds, capped at 300). The counter increments
once per failed attempt. A late process exit cannot close a newer attempt. A
pause records an interruption without consuming a failure. A lease expiry does
not prove process exit; unfinished runs still prevent another manager claim.

At the failure limit, the review enters `ESCALATED`, new work claims stop, and
both `run` and `serve` return that state. New triggers and urgency do not reset
failures. Inspect `review show ID` and `recover`, repair the cause, then explicitly
reset with `review retry ID --reason '...'`. Reset retains attempt history and
cannot proceed while a manager process is unverified. A fresh `run` respects the
same gate. When only a future retry remains, `run` returns `WAITING_FOR_REVIEW`
and `next_check_at` for an external supervisor instead of spinning.

Two additional runner controls govern successful normal reviews:

```json
{
  "manager_review_min_interval_seconds": 0,
  "manager_review_max_delay_seconds": 60
}
```

The default cooldown is zero. With a positive cooldown, normal reviews may wait
until the last successful review is old enough, while committed work continues.
The oldest pending normal request becomes eligible at the maximum delay. Urgent
reviews and planning when no committed READY task remains bypass this cooldown;
they do not bypass failure backoff. The existing first-trigger debounce remains
separate. Measure representative workloads before increasing these settings.

## Durable human attention

The same decision-attention projection feeds status JSON, the board, and the
operator report. It includes age, kind, affected nonterminal tasks/cases, and the
next retrieval command. `age_seconds` is elapsed time since the decision was
requested, computed against one observation time for a snapshot.

Reconciliation records `DECISION_NEEDS_ATTENTION`, `CASE_BLOCKED_ON_HUMAN`, and
`MISSION_BLOCKED_ON_HUMAN` when each scope enters a human wait, and
`HUMAN_BLOCK_CLEARED` when it leaves. Human kinds are `human_decision`,
`missing_access`, and `safety_stop`. A case transition means that case has human
blocked work; the mission transition additionally requires no committed READY or
active task. Other work may continue while a case needs attention. Paused missions
are not classified as globally blocked by a human.

A transition has a durable version and blocked-since timestamp. Repeated polls do
not repeat it; leaving and reentering creates another version. Optional positive
`decision_escalation_seconds` in runtime limits emits `DECISION_AGING` once per
decision and threshold. No elapsed-time rule answers a decision or grants consent.
Notification routing is described in [delivery extensions](EXTENSIONS.md#event-notifications).
