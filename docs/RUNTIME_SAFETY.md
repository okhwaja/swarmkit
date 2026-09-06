# Durable runtime and recovery

This is the normative contract for the runtime added in 0.7.0. Swarmkit supports
one user on one POSIX host (macOS or Linux). The harness and its tools enforce
permissions and credentials. These commands coordinate work; they do not grant
authority or intercept arbitrary tool calls.

## Stop, restart, and change direction

All examples assume `SWARM_ROOT` points at a mission initialized with `init`.

```bash
python3 swarmctl.py pause --reason 'Investigate a change of plans'
python3 swarmctl.py recover
python3 swarmctl.py why
python3 swarmctl.py resume --reason 'Continue the current plan'
python3 swarmctl.py run --max-cycles 20
```

`pause` immediately stops new task, manager, delivery, and harness claims and
fences active task writes. Existing processes may still be running, including
external operations already submitted. It retains their run records and changes
executing effects to `UNKNOWN`. It is not an OS kill switch. `drain` stops new
claims while allowing existing task attempts to checkpoint and complete. The
scheduler changes `DRAINING` to `PAUSED` after its active work finishes. An idle
operator can resume a drained mission after verifying quiescence with `recover`.

`cancel --reason ...` permanently cancels pending work and waits, preserving
history and uncertain effects. `abandon --reason ...` records permanent escalation
when cleanup cannot be guaranteed. Neither deletes files nor assumes that a
remote action was reversed. Inspect `recover`, `effect list`, and `workspace list`
for outstanding processes, actions, and changes. Terminal missions cannot resume.
Cancelling an individual task also cancels its dependency descendants.

A mission has a separate durable desired state and an outcome. `why` explains
claims, missing decisions, dependencies, limits, unfinished runs, and uncertain
effects. `status` includes `runtime`. Mission success, cancellation, abandonment,
and scheduler budget/escalation dispositions are recorded separately from task
states. Uniform typed outcomes for every case and workstream remain future work.

## Crash-safe runs and attempts

Every claim creates an attempt with generation, fresh agent identity, mission
revision, timestamps, and disposition. Use a new `--agent` value on each reclaim;
an identity may not be reused for the same task. Checkpoint/complete/block/wait,
evidence, and effect writes acquire a write lock before checking ownership.

`run` holds a single-host OS controller lock. Each harness run holds its own lock,
inherited by the child process. A controller crash releases the controller lock,
but the child retains its run lock until it exits. `recover` only closes an
unfinished run automatically when that lock is free. It records interruption and
requeues eligible work; uncertain external effects still block a new claim.
`run` returns `RECOVERY_WAIT` while an earlier live or unverified run remains.
Do not delete lock files. The dispatcher owns its subprocess group and terminates
remaining group members when a run ends or times out. Harnesses must not detach
background work into unrelated process groups.

Pre-0.7 unfinished runs have no process lock. After independently confirming the
process stopped, use `recover --abandon-run RUN_ID --reason 'process stopped ...'`.
This command records an operator assertion, not an automatic liveness proof.
Leases still fence writes. Recovery does not make a stale process trustworthy.

## Track an external action

The effect ledger is an explicit integration protocol. For a claimed task:

```bash
python3 swarmctl.py effect prepare --task TASK --agent ATTEMPT_AGENT \
  --key 'provider:object:revision:action' --target 'provider/object' \
  --revision EXACT_REVISION --parameters '{"operation":"approve"}'
python3 swarmctl.py effect start EFFECT --actor ATTEMPT_AGENT
# Perform the action through the harness tool, using the same provider idempotency key.
python3 swarmctl.py effect succeeded EFFECT --actor ATTEMPT_AGENT --receipt 'provider receipt'
```

`prepare` deduplicates the exact task, target, revision, and parameters. Reusing a
key with different parameters fails. `start` atomically changes `PREPARED` to
`EXECUTING`, requires current ownership and decision acknowledgments, and cannot
be repeated. A crash after `start` makes the result uncertain. Query the provider,
then use `succeeded`, `failed`, `unknown`, or `not-applied` with a receipt or
observation. Failure alone never enables automatic replay. `not-applied` must be
supported by provider evidence that no action happened. A fresh attempt may adopt
a `PREPARED` or `NOT_APPLIED` intent by calling `prepare` with its original key.
A `SUCCEEDED` intent is returned as completed and must not be executed again.

`complete`, reclaim, and mission resume refuse unresolved executing/unknown
effects. The ledger cannot guarantee exactly-once behavior from a provider that
offers neither idempotency nor a reliable way to query results. Integration code
must recheck the current target revision and tool authority immediately before
submission. A receipt is recorded evidence, not independently authenticated proof.

## Confirmation and reliable inbox delivery

Use `task block --kind human_decision` to persist the concrete question, options,
and recommendation. Resolution survives restart; a fresh attempt claims the task
and acknowledges the current decision version before continuing. Use
`decision require-choice` when a branch requires a particular answer. An answer
of “no” is a decision to honor, not implicit permission merely because work woke.
Revised decisions invalidate old acknowledgments. No approval is inferred from
elapsed time or from a harness exit code.

```bash
python3 swarmctl.py inbox --agent ATTEMPT_AGENT --task TASK --lease --limit 50
# Apply the events using their stable event IDs and idempotent commands.
python3 swarmctl.py inbox --agent ATTEMPT_AGENT --ack DELIVERY_TOKEN
```

A batch is retained until acknowledged. Expiry redelivers the same events with a
new token; an expired token cannot acknowledge the new delivery. Acknowledgment
is idempotent and recipient-bound. Each task scope has a separate offset, so
reading one task does not consume another task's events. Delivery is at least
once: the handler must deduplicate mutations using event IDs or planning/effect
keys. Legacy `--advance` is retained for compatibility and is unsuitable when a
crash between reading and acting would lose important information.

## Isolate files and scarce resources

```bash
python3 swarmctl.py workspace create --task TASK --repository /path/to/repo --base BASE_REF
python3 swarmctl.py resource acquire pipeline/staging --task TASK --agent ATTEMPT_AGENT
python3 swarmctl.py resource release LEASE_TOKEN --agent ATTEMPT_AGENT
```

Create a worktree before claiming an editing task. Its resolved base commit,
branch, path, and task are durable, and dispatch uses it as the working directory.
The original checkout is untouched. Worktrees are retained for explicit human or
integration-owner inspection; automatic deletion is intentionally absent. If Git
created a worktree but the process crashed before registration, inspect Git's
worktree list and reconcile it manually before retrying creation.

Resource leases are exclusive, task/attempt-bound, and no longer than the task
lease. A new owner cannot take an expired resource from an unfinished harness or
an uncertain effect. Stale release tokens cannot release a replacement lease.
Callers must use these leases consistently and external systems must enforce
fencing where possible. Swarmkit cannot prevent a tool that ignores the protocol
from modifying the same resource. Shared/read locks and cross-mission locks are
not implemented.

## Evidence and bounded context

```bash
python3 swarmctl.py evidence contract --task TASK --revision EXACT_REVISION --environment ENV
python3 swarmctl.py configure --strict-evidence on
# After claiming and performing the check, capture its output in a result file.
python3 swarmctl.py evidence record --task TASK --agent ATTEMPT_AGENT \
  --criterion 'Exact acceptance criterion' --revision EXACT_REVISION --environment ENV \
  --command 'actual test command' --exit-code 0 --path /path/to/result.log
python3 swarmctl.py evidence gaps --task TASK
```

A task with an evidence contract, or any task in strict mode, cannot complete
until every criterion has successful evidence for the exact contracted revision,
environment, task generation, and mission revision. Result files are registered as verification artifacts for optional audit export;
their hashes are rechecked at completion. Failed, stale, missing, or changed files do not count.
The manager sets the contract before a claim; a new verification task can target
the final implementation revision. The harness is responsible for running the
reported command honestly. This is an evidence coverage/integrity contract, not
a trusted test execution service. Legacy missions retain free-text verification
unless strict mode or a task contract is enabled.

Invocation contexts are read in one SQLite snapshot and carry an event watermark.
Prompt files have unique names and are created exclusively; run events record
their SHA-256 and selected model. Lists and long strings are bounded; omitted
items contain retrieval instructions. Context above 64 KB becomes a compact
retrieval packet rather than silently dropping unmarked state. Fetch the current
full task, decisions, and constraints before acting on any truncated packet.
Role guidance is additional to this context limit.

## Planning, amendments, limits, and services

Use `task add --idempotency-key KEY` for retriable planning. An identical retry
returns the same task; a conflicting specification fails. Existing policy stage
dependencies provide fan-out and a fan-in barrier. The reducer's acceptance
criteria must require reconciling all inputs and contradictions.

In strict mode, a successful manager process does not complete its review until
it calls `review-commit REVIEW --agent AGENT --summary ... --dispositions JSON`.
Supply a list in trigger order with `disposition` (`acted`, `deferred`, or
`no-change`) and a nonempty `rationale` per trigger. Review retries invalidate the
previous commit; every retry must explicitly review its current trigger batch.
The full commit remains in the event history.

Pause, drain/recover live harnesses, and reconcile uncertain effects before:

```bash
python3 swarmctl.py amend --objective 'Revised objective' --success 'Revised criterion' \
  --constraint 'Current boundary' --reason 'Changed priorities'
python3 swarmctl.py configure --limits '{"max_tasks":100,"max_runs":200,"max_attempts_per_task":3}'
python3 swarmctl.py resume --reason 'Manager may review revised plan'
```

Amendment increments mission revision and saves old/new specifications. Remaining
work loses scheduling authorization, including blocked and externally waiting
tasks. The manager explicitly adopts or replaces it. Completed work remains
historical evidence; it is not automatically proof of the revised objective.

`max_attempts_per_task` bounds failed/interrupted/expired attempts (default 3).
Normal confirmation waits and external checks do not spend this failure budget.
`max_runs`, `max_tasks`, and an RFC3339 `deadline` are optional persistent limits.
An exhausted task is explained by `why`; when no eligible work remains, `run`
records `ESCALATED`. Raise an explicit limit to authorize another attempt.
Money, token, provider API, and human-attention accounting require integrations
and are not estimated from elapsed time.

For a service, `serve --max-polls 120 --poll-seconds 30 --max-cycles 20` repeatedly
reconciles durable ingress and waits using the same single-controller runtime.
It returns on pause, terminal state, budget exhaustion, or escalation. Cases and
signals remain idempotent across restarts. Configure an OS service separately if
reboot autostart is needed; no launch agent or daemon is installed automatically.
Provider ingress should use an external ID containing object identity and exact
revision; provider-specific supersession and stale-approval checks remain the
ingress/action adapter's responsibility.

Optional `runner.json` `escalation_models` maps roles to a model for subsequent
task generations, falling back to `models`. Selection and generation are audited.
This simple routing is attempt-based; it does not classify ambiguity, costs, or risk.

## Inspect and share a consistent run

```bash
python3 swarmctl.py why
python3 swarmctl.py export --output private-audit.zip --include-artifacts
python3 swarmctl.py export --output shareable-telemetry.zip --share-safe
python3 swarmctl.py audit-verify private-audit.zip
```

Exports freeze SQLite once and derive snapshot, board, events, health, and
attempt-level `explanation.json` from that copy. Artifact bytes that differ from
registration are omitted and reported. The manifest hashes all included bytes;
`audit-verify` checks hashes, sizes, missing/extra entries, and duplicate entries.
It verifies integrity relative to the manifest, not authenticity of its author.
Run files copied while a harness is active reflect the bytes available at export;
finish/drain runs first when a complete log archive is required.

A full export is private and includes raw SQLite, prompts, logs, paths, and
payloads. `--share-safe` instead emits only allowlisted structural state/counts
and the manifest; it excludes free text, entity IDs, paths, artifacts, receipts,
and the database. It is deliberately less useful for detailed postmortems.

## Upgrade

Known schema versions 1–6 upgrade transactionally to schema 7. Versions 2–6 were
additive table releases; their compatible table definitions are replayed before
the version 7 runtime tables. Each version step and final metadata update occur
inside one write transaction. A failed migration rolls back, and unknown/newer
versions fail instead of being relabeled. Stop old controllers before upgrading;
back up the mission directory before moving between releases. Old history is
retained; new attempt records begin with the first post-upgrade claim.
