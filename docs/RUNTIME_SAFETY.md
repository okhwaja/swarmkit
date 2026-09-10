# Durable runtime and recovery

This is the normative runtime contract, including the 0.11.0 evidence diagnostics and retry contract. Swarmkit supports
one user on one POSIX host (macOS or Linux). The harness and its tools enforce
permissions and credentials. These commands coordinate work; they do not grant
authority or intercept arbitrary tool calls.

## Stop, restart, and change direction

All examples assume `SWARM_ROOT` points at a mission initialized with `init`.

```bash
swarmctl pause --reason 'Investigate a change of plans'
swarmctl recover
swarmctl why
swarmctl resume --reason 'Continue the current plan'
swarmctl run --max-cycles 20
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

For a whole workstream, use `workstream update WS-ID --status CANCELLED --summary 'Reason for cancellation'`. A non-empty summary is required. Cancellation
retires unfinished linked tasks and their unfinished dependency descendants,
including dependents in other workstreams. Completed results remain intact and
uncertain actions remain available for reconciliation. For a case-owned workstream,
use `case cancel CASE-ID --reason '...'` to close both together. Other workstream
statuses describe progress; they do not pause or resume workers.

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
An unexpected supervision error leaves the run unfinished: an exception is not
proof that its child stopped. The controller stops allocating more work, lets
other supervised runs finish, and directs the operator to `recover`. Log paths
are recorded before launch and remain discoverable even when supervision fails.
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
swarmctl effect prepare --task TASK --agent ATTEMPT_AGENT \
  --key 'provider:object:revision:action' --target 'provider/object' \
  --revision EXACT_REVISION --parameters '{"operation":"approve"}'
swarmctl effect start EFFECT --actor ATTEMPT_AGENT
# Perform the action through the harness tool, using the same provider idempotency key.
swarmctl effect succeeded EFFECT --actor ATTEMPT_AGENT --receipt 'provider receipt'
```

`prepare` deduplicates the exact task, target, revision, and parameters. Reusing a
key with different parameters fails. `start` atomically changes `PREPARED` to
`EXECUTING`, requires current ownership and decision acknowledgments, and cannot
be repeated. A crash after `start` makes the result uncertain. Query the provider,
then use `succeeded`, `failed`, `unknown`, or `not-applied` with a receipt or
observation. Failure alone never enables automatic replay. `not-applied` must be
supported by provider evidence that no action happened. A fresh attempt may adopt
a `PREPARED` intent by calling `prepare` with its original key. After confirmed
`NOT_APPLIED`, the current owner (including the same attempt) may explicitly call
`prepare` with that key to authorize another start. This clears the old receipt
from the current intent while preserving it in events. Identical reconciliation
retries return the recorded result without another event; a conflicting terminal
receipt or outcome is rejected.
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
swarmctl inbox --agent ATTEMPT_AGENT --task TASK --lease --limit 50
# Apply the events using their stable event IDs and idempotent commands.
swarmctl inbox --agent ATTEMPT_AGENT --ack DELIVERY_TOKEN
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
swarmctl workspace register --task TASK --repository /path/to/source \
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
Create before claiming, or supply `--agent` when the current owner creates it during an attempt. The argv placeholders are `{repository}`
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
process group. Before invoking a provider, Swarmkit commits a creation record as
`UNKNOWN` with the exact argv and persistent stdout/stderr paths. A controller
crash, timeout, nonzero exit, or malformed receipt cannot authorize a replay, even
when the provider chose a path other than the suggested destination. Only a proven
failure to start the process is automatically recorded as `NOT_CREATED` and retryable.
Do not create detached background processes in a checkout adapter.

Inspect incomplete creation using `workspace attempts --task TASK`, `why`, or
`doctor`. `workspace attempts` defaults to the latest 50 records (`--limit` 1–500); add
`--pending` to focus on uncertain or unattached creations.
After checking the internal CLI/provider, record what actually happened:

```bash
# A checkout exists. Record its exact path and starting revision.
swarmctl workspace reconcile WC_ID --outcome created \
  --observation "Provider lookup returned checkout 42" \
  --path /absolute/actual-checkout --base-revision EXACT_REVISION \
  --workspace-ref OPTIONAL_CHECKOUT_NAME
# Repeat the original create request to attach that recorded checkout.
swarmctl workspace create --task TASK --repository /path/to/source --base BASE

# Or, only after proving no checkout was created, allow a fresh invocation.
swarmctl workspace reconcile WC_ID --outcome not-created \
  --observation "Provider lookup found no checkout for this request"
```

Reconciliation is refused while a live adapter retains the creation lock, even
if its controller has died. Observations remain in the audit trail. They are an
operator/harness assertion, not automatic verification by Swarmkit. A reconciled
outcome cannot be changed to a conflicting outcome. Checkouts are never deleted.

A valid success receipt becomes `CREATED` before task attachment. If a pause or
expired owner prevents attachment, a later eligible owner repeats `workspace create`
to attach it and mark it `REGISTERED`, without calling the provider again. Provider,
source, and requested base must still match. Reconciliation is available during a
pause or after cancellation; attachment still obeys task ownership and lifecycle
rules. Terminal tasks retain the creation record for explicit operator cleanup.
Manual `workspace register` cannot bypass a pending creation record. Claims and
dispatch refuse a checkout that still needs reconciliation or attachment. The
scheduler reports `WAITING_FOR_WORKSPACE` without consuming worker attempts when
checkout recovery is the remaining gate. Checkout state is re-read under the run
registration transaction so concurrent creation cannot launch in a stale directory.

Uncertain creation also keeps a drain pending and blocks resume, amendment, and
mission completion. Observe the provider first; `CREATED` records do not imply a
live process and may be attached after resume. An unregistered suggested destination
already on disk still requires inspection before any new creation. Python callers
must invoke creation/reconciliation outside an existing transaction: the intent
must be durable before the external command starts.

Dispatch uses the registered directory regardless of VCS, and refuses a missing
checkout. Swarmkit retains checkouts for explicit inspection/integration and does
not invoke Git to inspect or clean up manual/command workspaces. Existing Git
registrations continue to dispatch after upgrade; future creation must select
Git explicitly. Without a provider, `workspace create` explains how to configure
an adapter or register a checkout instead of attempting Git.

Resource operations remain VCS-independent:

```bash
swarmctl resource acquire pipeline/staging --task TASK --agent ATTEMPT_AGENT
swarmctl resource release LEASE_TOKEN --agent ATTEMPT_AGENT
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
swarmctl evidence contract --task TASK --revision EXACT_REVISION --environment ENV
swarmctl configure --strict-evidence on
# After claiming and performing the check, capture its output in a result file.
swarmctl evidence record --task TASK --agent ATTEMPT_AGENT \
  --criterion 'Exact acceptance criterion' --revision EXACT_REVISION --environment ENV \
  --command 'actual test command' --exit-code 0 --path /path/to/result.log
swarmctl evidence gaps --task TASK
swarmctl evidence show --task TASK
swarmctl evidence list --task TASK --limit 20
```

`evidence show` explains each criterion using the record that actually governs
completion: `MISSING`, `STALE` (with the mismatched target/attempt fields), `FAILED`
(with the exit code), `FILE_UNAVAILABLE`, `FILE_CHANGED`, or `PASSED`. A missing
contract or invalid criteria appear in `gaps`. `evidence list` returns newest-first
`records` and `next_before`; pass that ID to `--before` for the next page. Its default
limit is 50 and maximum is 500. History ordering uses insertion order, including
records made in the same second; concurrent new records do not shift older pages.

Use `evidence record --idempotency-key CHECK_ID` when retrying a recording command
after a lost acknowledgment. Keep that key stable for that exact task attempt,
criterion, target, command, exit code, and result path/contents. An exact retry
returns the original evidence ID without changing its insertion order or adding
artifacts/events. A real rerun needs a new key. Changed requests are rejected,
and current ownership and decision acknowledgments are still required on retries.
Without a key, each call intentionally appends a new result.

A task with an evidence contract, or any task in strict mode, cannot complete
until every criterion has successful evidence for the exact contracted revision,
environment, task generation, and mission revision. Result files are registered as verification artifacts for optional audit export;
their hashes are rechecked at completion. The newest record for each criterion
on that contracted target/attempt is authoritative: a later failed rerun blocks
completion even if an older passing file is retained. A new successful record can
restore coverage. Evidence for another revision or environment does not supersede
the contracted target. Failed, stale, missing, or changed files do not count.
Evidence and its artifact share one file hash observation; each distinct result
path is hashed once per completion check even when it covers several criteria.
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
For one case, `case apply-policy --replace --idempotency-key KEY --reason TEXT`
atomically retires unfinished work and installs a reviewed workflow. Its
[case planning contract](PERSISTENT_SERVICES.md#adopt-or-replace-a-case-plan)
defines retry identity, retained decisions, and live-work guards.

In strict mode, a successful manager process does not complete its review until
it calls `review-commit REVIEW --agent AGENT --summary ... --dispositions JSON`.
Supply a list in trigger order with `disposition` (`acted`, `deferred`, or
`no-change`) and a nonempty `rationale` per trigger. Review retries invalidate the
previous commit; every retry must explicitly review its current trigger batch.
The full commit remains in the event history.

Pause, drain/recover live harnesses, and reconcile uncertain effects before:

```bash
swarmctl amend --objective 'Revised objective' --success 'Revised criterion' \
  --constraint 'Current boundary' --reason 'Changed priorities'
swarmctl configure --limits '{"max_tasks":100,"max_runs":200,"max_attempts_per_task":3}'
swarmctl resume --reason 'Manager may review revised plan'
```

Amendment replaces the entire objective, success-criterion list, and constraint
list; omitted criteria and constraints are not retained. It increments mission
revision and saves old/new specifications. Remaining
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
swarmctl why
swarmctl export --output private-audit.zip --include-artifacts
swarmctl export --output shareable-telemetry.zip --share-safe
swarmctl audit-verify private-audit.zip
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

Known schema versions 1–12 upgrade transactionally to schema 13. Versions 2–6 were
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
requires inspecting the provider, recording `workspace reconcile`, and attaching
any recovered receipt with `workspace create`; no automatic provider retry or
checkout deletion is implied.

## Schema 10 upgrade

Version 0.9.0 adds the checkout creation journal and its pending-task uniqueness
constraint. Existing workspace registrations are unchanged. Old releases have no
durable record of an unregistered provider operation; inspect those checkouts
manually before adopting this release. Stop old controllers and keep a backup
before upgrade. Older binaries cannot read schema 10.

## Schema 11 upgrade

Version 0.10.0 indexes the identity of each stored manager-review trigger and
adds a pending-review ordering index. Trigger payloads remain in their original
ordered JSON; the new table accelerates identity lookup, and writes update both
in the same transaction. Existing oversized reviews are preserved. New batches
are limited to 50 triggers, with no trigger dropped. Stop old controllers and
back up before upgrading; older binaries cannot read schema 11.

Private exports include `intake-export.json`, which lists copied case/signal
payloads and those omitted because they were missing, outside intake, or changed.
Copied bytes are checked against the recorded intake hash and size after copying.
An archive can pass `audit-verify` while reporting missing source evidence: archive
integrity is separate from completeness of the original mission's evidence.


## Schema 12 upgrade

Version 0.11.0 adds an optional task-scoped evidence key table and indexes for the
latest criterion/target result and task history. No existing evidence payload,
hash, result order, or artifact is rewritten. Completion reads one indexed result
per criterion instead of scanning verification history. Stop older controllers
and back up before upgrading; older binaries cannot read schema 13.


## Runtime files in private exports

Private exports copy ordinary files from `prompts`, `runs`, and `outbox`. They omit
process locks, runtime symlinks, and special files such as FIFOs instead of following
links into unrelated directories. `runtime-export.json` records skipped links,
special files, and files that disappear or become unreadable during copying.
Explicit registered artifacts are handled separately by `--include-artifacts`,
the size limit, and recorded hash checks.

If an intake payload or artifact disappears between inspection and copying,
the archive retains its canonical database record and explains the missing file
in `intake-export.json` or `artifact-export.json`. Review these omission reports
alongside `audit-verify`: an intact archive can have incomplete source evidence.

## Inspect coordination problems

`doctor` reads state without reconciling or repairing it. It reports structured
problems and returns a nonzero exit code for integrity errors, including malformed
stored timestamps/JSON and unavailable evidence files. Duplicate active task titles
are compared within a workstream; repeated workflow titles in independent cases
are expected. If an older cancelled workstream still contains unfinished tasks,
inspect and explicitly cancel that work with a recorded reason.

## Explicit choice edits and informational references

`decision revise ID --answer '...'` preserves its stored structured option.
Supply `--choice` to replace it with another exact offered option, or
`--clear-choice` to remove it. The flags are mutually exclusive. Each revision
still advances the decision version, retires obsolete attempts, and requires
fresh acknowledgments; preserving the option does not prove revised conditions
passed. The audit event records old/new choices and preserve/set/clear intent.
Legacy prose-only decisions are not guessed or automatically repaired.

`decision link ID --task TASK` remains an authoritative relation: it can block the
task and retire active ownership. Use `decision reference ID --task TASK` only
for informational context. References appear in task prompts and retrieval but
never gate readiness, require acknowledgment, retire an attempt on revision, or
keep a decision alive when all its authoritative tasks are terminal. There is no
implicit conversion of old gates into references.

## Task acceptance amendments

Use `task amend` when the task outcome is still the same but its acceptance
criteria need correction. Read `task show` first, then supply the complete new
criteria, the expected acceptance revision, a rationale, and an idempotency key:

```sh
swarmctl task amend TASK --expected-revision 1 \
  --acceptance 'Existing required check' --acceptance 'Additional check' \
  --reason 'Include newly identified coverage' --idempotency-key coverage-2
swarmctl task approve TASK --actor human
```

The task must be nonterminal and quiescent: no active owner, unfinished harness,
active external wait, uncertain/executing effect, or pending workspace creation.
Unresolved claimed/unknown deliveries also prevent amendment because deliveries
are not generally attributable to a single task. Interrupt/drain and reconcile
first when necessary. Policy-owned criteria must be changed through explicit
policy-plan replacement; this command does not silently override a policy stage.

An amendment retains the task ID, dependencies, artifacts, and old criteria in
`acceptance_revisions`. It deauthorizes the task and increments
`acceptance_revision`; approval is separate. The next claim creates a fresh
attempt generation and agent identity. Attempts, evidence, prompts, and completion
carry the acceptance revision. Old evidence remains available but cannot satisfy
the new contract, even if some criterion text is unchanged. Reusing an amendment
key returns the original revision only for the exact same change.

Conditional external-action authority is specified in
[conditional grants](CONDITIONAL_GRANTS.md). Review retry gates and staged plan
publication are specified in [responsive orchestration](RESPONSIVE_ORCHESTRATION.md).

The schema 13 migration adds review-attempt and retry state, staged task
publications, acceptance revisions, informational decision references, attention
transitions, notification cursors, and conditional-grant records. Existing task
attempts and evidence receive acceptance revision 1. An existing RUNNING review
retains its lease and receives an initial attempt record. Its unowned nonterminal
tasks are conservatively staged until that review is recovered and completed.
Stop controllers before upgrading; do not run old and new binaries concurrently. No current decision
choice is inferred or changed during migration. Unknown and future schema
versions remain rejected, and a failed migration rolls back the complete upgrade.

`serve` reports `poll_budget_exhausted` and a next action when its configured poll
count runs out. The default 120 polls have 119 thirty-second pauses plus actual run
time; this is not a fixed lifetime or an installed background service. An external
supervisor must arrange subsequent wakes, including `WAITING_FOR_REVIEW` times.
