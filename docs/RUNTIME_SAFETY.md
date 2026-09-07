# Durable runtime and recovery

This is the normative runtime contract, including the 0.8.0 reliability and usability changes. Swarmkit supports
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
states. Case and workstream `completion_outcome` fields distinguish successful, partial,
and cancelled task histories. Their lifecycle can be `DONE` while their result is
`PARTIAL`; stopping work is different from delivering all planned work.

## Crash-safe runs and attempts

Every claim creates an attempt with generation, fresh agent identity, mission
revision, timestamps, and disposition. Use a new `--agent` value on each reclaim;
an identity may not be reused for the same task. Checkpoint/complete/block/wait,
evidence, and effect writes acquire a write lock before checking ownership.

`run` holds a single-host OS controller lock. Each harness run holds its own lock,
inherited by the child process. A controller crash releases the controller lock,
but the child retains its run lock until it exits. `recover` covers both worker and delivery runs. It only closes an
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
Acknowledgments belong to the currently leased task owner. Each fresh attempt
acknowledges the current answer itself, even if the answer did not change.
Revising or newly linking a decision retires an active attempt, marks its executing
effects uncertain, and closes any obsolete external-wait subscription. Closing a
subscription does not claim the provider job stopped or succeeded. No approval is inferred from
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

Both plain reads and leased reads return at most `--limit` events (default 50,
maximum 500). Use `--after` with the last returned `seq` to inspect the next page;
plain reads never advance the offset. Task scoping is resolved within SQLite, so
large case histories do not become oversized parameter lists or get decoded just
to return a small batch. Legacy advancement also respects task scopes and the
caller's transaction. Lease durations must be positive integer seconds.

## Isolate files and scarce resources

Swarmkit does not assume a VCS. An isolated workspace is an existing directory,
an exact provider-specific revision identifier, an optional checkout reference,
and its task. There are three ways to supply one:

- **Harness-managed (default):** the harness uses its known jj/internal checkout
  tools, then registers the resulting directory and revision.
- **Command adapter:** configure the local checkout CLI once in `runner.json`.
  Swarmkit invokes it directly and registers its JSON receipt.
- **Git:** opt into the built-in worktree provider with `--provider git` or
  `"workspace": {"provider": "git"}`. Git is never autodetected or assumed.

For a checkout already created by the harness or operator:

```bash
python3 swarmctl.py workspace register --task TASK --repository /path/to/source \
  --path /path/to/isolated-checkout --base-revision EXACT_PROVIDER_REVISION \
  --workspace-ref OPTIONAL_CHECKOUT_NAME
```

Register before dispatch so the harness launches in the correct directory. An
already active task requires `--agent ATTEMPT_AGENT` and current ownership; its
harness must switch its own tools to that directory. Registration cannot change
an existing process's cwd. A task's registration is immutable; conflicting source,
path, revision, reference, or provider is rejected. The source and checkout must
be distinct existing directories, and a checkout cannot belong to two tasks.
Adapters/harnesses remain responsible for actual isolation (for example avoiding
shared writable files); directory registration cannot prove isolation by itself.

A command adapter is usually the most efficient choice for a repeatable internal
CLI: discovery happens once during setup instead of in every model invocation.
Add this object to `runner.json` (the command below is illustrative, not a claim
about your internal CLI's syntax):

```json
{
  "workspace": {
    "provider": "command",
    "command": [
      "/absolute/path/to/checkout-adapter",
      "--source", "{repository}",
      "--destination", "{path}",
      "--revision", "{base}",
      "--request-id", "{task_id}"
    ],
    "timeout_seconds": 300
  }
}
```

Then run `workspace create --task TASK --repository /path/to/source --base BASE`.
Creation happens before claiming a task. The argv placeholders are `{repository}`
(absolute source directory), `{path}` (suggested task-specific destination),
`{base}` (opaque revision expression), `{task_id}` (stable request key), and `{root}`
(absolute mission directory). Each expanded argument is passed without a shell,
with the source as cwd. Literal braces in argv strings must be doubled.

The adapter may directly be the internal CLI if it supports this output contract;
otherwise use a small wrapper. It must print one JSON object on stdout and send
progress messages to stderr:

```json
{"path":"/absolute/actual-checkout","base_revision":"exact-internal-revision","workspace_ref":"optional-name"}
```

`path` must be an existing absolute directory. `base_revision` must identify the
actual immutable starting revision, even if `--base` was a moving expression.
`workspace_ref` is optional: it can be a jj workspace name, an internal checkout
ID, or a Git branch. Swarmkit never interprets these as Git syntax. The historical
SQLite/API `branch` field remains an alias for the opaque `workspace_ref`.
The actual path may differ from the suggested destination when the internal CLI
allocates checkout locations itself. Providers should deduplicate requests using
`task_id`; a registered identical create request returns its original receipt.

Commands have a bounded timeout, at most 64 KB of JSON receipt text, and an owned
process group. Nonzero exit, timeout, invalid receipts, missing directories, or
a task becoming ineligible during creation prevent registration. The command may
still have created a checkout: Swarmkit does not automatically retry or delete
it. Inspect it, then use `workspace register` if appropriate. An unregistered
suggested destination already on disk also requires inspection before retry.
Do not create detached background processes in a checkout adapter.

Dispatch uses the registered directory regardless of VCS, and refuses a missing
checkout. Swarmkit retains checkouts for explicit inspection/integration and does
not invoke Git to inspect or clean up manual/command workspaces. Existing Git
registrations continue to dispatch after upgrade; future creation must select
Git explicitly. Without a provider, `workspace create` explains how to configure
an adapter or register a checkout instead of attempting Git.

Resource operations remain VCS-independent:

```bash
python3 swarmctl.py resource acquire pipeline/staging --task TASK --agent ATTEMPT_AGENT
python3 swarmctl.py resource release LEASE_TOKEN --agent ATTEMPT_AGENT
```

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
The manager can pin the contract before a claim, especially for independent
verification of a known revision. When an implementation produces its revision
only after work begins, the current owner may bind the first contract using
`evidence contract --actor ATTEMPT_AGENT`. That owner must acknowledge current
decisions first and cannot replace an already pinned contract during the attempt.
An identical contract retry has no extra event. Use fresh verification if the
pinned target needs to change. This works with opaque provider revisions, including
jj/internal identifiers; no Git commit format is assumed. The harness is responsible for running the
reported command honestly. This is an evidence coverage/integrity contract, not
a trusted test execution service. Legacy missions retain free-text verification
unless strict mode or a task contract is enabled.

Invocation contexts are read in one SQLite snapshot and carry an event watermark.
Prompt files have unique names and are created exclusively; run events record
their SHA-256 and selected model. Database queries select bounded pages before
building context. A worker reads its task and related state rather than every
finished task in the mission. Case signals are newest first, so an old comment
history cannot hide the most recent revision or human response.

Pages carry `items`, `has_more`, and an explicit retrieval command. Context includes
the runtime lifecycle/revision, registered checkout, and task evidence contract.
Lists and long strings are bounded to a 64 KB JSON budget; progressive reduction
preserves the mission and task identity. Truncation is marked, and agents must fetch
full task, decision, or constraint data before relying on its completeness. Role
guidance and pretty-print whitespace are additional to this context budget.

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

Private exports freeze SQLite once without reconciling that historical copy, and derive snapshot, board, events, health, and
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

Known schema versions 1–8 upgrade transactionally to schema 9. Versions 2–6 were
additive table releases; their compatible table definitions are replayed before
the version 7 runtime tables. Schema 8 adds workspace provider and requested-base
metadata; existing registrations retain provider `git`. Schema 9 adds indexes for
scoped event and context queries and marks legacy deliveries with known ambiguous
run/lease error records `UNKNOWN`, requiring provider reconciliation. It also adds
case/workstream completion outcomes and distinguishes old automatic intake closure
from explicitly cancelled cases. Each version step and final metadata update occur
inside one write transaction. A failed migration rolls back, and unknown/newer
versions fail instead of being relabeled. Stop old controllers before upgrading;
back up the mission directory before moving between releases. Old history is
retained; new attempt records begin with the first post-upgrade claim.

## Delivery uncertainty

Delivery adapters use the same streaming logs, owned subprocess groups, and inherited
process locks as worker harnesses. A missing provider acknowledgement, timeout,
expired claim, or interrupted delivery becomes `UNKNOWN`; it is never automatically
returned to the send queue. Use `recover`, inspect the provider, then record
`delivery reconcile --outcome sent|not-sent --receipt ...`. Only a proven non-delivery
returns the job to `PENDING`. See [delivery operations](EXTENSIONS.md).

Final reports can be sent after finite task work is complete. Paused, cancelled,
or abandoned missions still reject new delivery claims. Mission completion and
provider-confirmed report delivery are separate recorded outcomes.

## Honest completion

A task needs a non-empty result and verification statements. Cases and workstreams
report `completion_outcome` separately from their lifecycle state. A mixed history
of completed and cancelled tasks is conservatively `PARTIAL`; this does not prove
that every mission criterion was met or missed.

`mission complete` defaults to `PARTIAL` when any tasks were cancelled, otherwise
`SUCCEEDED`. A manager may explicitly select `--outcome SUCCEEDED` when its evidence
explains why cancelled approaches were obsolete and all actual success criteria
were met. Repeating identical completion is idempotent; conflicting new completion
evidence is rejected. Reports and scheduler results include the recorded outcome.

Cancellation withdraws open decisions only when none of their affected tasks remain
active. It never answers the question on the human's behalf.

## Schema 9 upgrade

Version 0.8.0 upgrades schema 8 transactionally to schema 9. The migration adds
bounded-context and unfinished-run indexes, case/workstream completion outcomes,
policy application retry keys, and signal/task identity links. Existing links are
recovered from structured wakeup events. Historical mixed completion becomes
`PARTIAL`; explicit case cancellations remain permanent. Known old ambiguous
delivery errors become `UNKNOWN` and require provider reconciliation.

Stop older controllers and keep a pre-upgrade backup before opening a mission
with 0.8.0. The prior binary cannot read the upgraded schema. Migration failure
rolls back rather than relabeling a partially upgraded database. No Git migration
or checkout conversion is involved.

## Initialization and local configuration

`init` takes a process lock and constructs the mission database in a private
staging directory. Schema, metadata, and the creation event commit together. The
closed database is published atomically; a failed initializer leaves no partial
canonical database that would prevent a retry. Existing `runner.json` is preserved.
The `.init.lock` file is an ownership mechanism and must not be deleted to bypass
a live initializer. Failed/crashed staging directories do not become missions.

Export publication is atomic: a failed build preserves any previous output. Choose
an output path outside the mission state directory so the archive cannot overwrite
its own source data. Event JSONL and archive files are streamed. Share-safe export
has a separate counter-only path; it never builds a private archive or copies
prompts, logs, payloads, or the database. Verification validates manifest structure,
relative paths, duplicate entries, sizes, and streaming content hashes; malformed
archives return problems rather than a Python traceback. Hash verification detects
content changes, not the identity or trustworthiness of the archive's author.

### Lifecycle across managers and delivery adapters

Pause retires the current manager-review lease as well as active worker attempts.
A late process exit cannot acknowledge the retired review; a fresh manager receives
it after resume. Cancel/abandon withdraw pending and running reviews. Drain allows
current workers, reviews, and claimed deliveries to finish and stays `DRAINING`
until every tracked harness process has closed, including a sender that already
recorded its receipt. Reconciliation then records `MISSION_DRAINED` and `PAUSED`.
Resume requires delivery runs and claims to finish or be recovered, and uncertain
deliveries to be reconciled, just as with uncertain effects.

A claimed or `UNKNOWN` delivery cannot be cancelled into a misleading terminal
state. Observe its provider outcome first; a live sender may still record its
receipt. Confirmed not-sent work can subsequently be cancelled while pending.

An active task owner can call `workspace create --agent AGENT` with the configured
command or explicit Git provider. Stale/nonowners are rejected before the checkout
command runs. The active harness must change to the returned directory itself;
subsequent dispatches use the registered path automatically. Checkout subprocesses
inherit the creation lock, so a controller crash does not permit another creator
while the original child is still alive. A failed/ambiguous checkout command still
requires inspecting the provider and registering any created checkout; no automatic
provider retry or checkout deletion is implied.
