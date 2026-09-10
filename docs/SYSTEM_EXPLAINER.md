# System explainer

For implementation ownership and transaction boundaries, see the [code map](CODE_MAP.md).

## What problem does this solve?

Suppose you tell a team of agents, “Our data pipeline is broken. Find out why and fix it.” You do not yet know whether the problem is in the source, queue, credentials, application code, destination, or monitoring. That means you cannot provide a detailed work plan.

The system lets you provide the outcome and safety boundaries instead. A manager agent investigates the problem in small steps, creates work when evidence supports it, and changes the plan as new information arrives.

The hard part is coordination. Agent conversations are temporary and can become stale. If one agent privately tells another about a decision, other workers may never learn it. Swarmkit therefore keeps important information in a shared database and records every meaningful change in an ordered event log.

## The pieces

### Mission

The mission is the result you want. It contains an objective, success conditions, constraints, phase, and completion evidence. It does not need to contain a detailed technical plan.

A finite mission ends when its outcome is proven. A service mission is a
persistent logical agent: it remains active while idle and accepts a sequence of
durable cases. The model conversations still remain short-lived.

### Cases and signals

A case is one idempotent inbound request with a dedicated workstream, initial
payload, tasks, policy, decisions, and result. A signal is an idempotent
follow-up such as an author reply, new revision, provider status, or comment.
Both are written before an agent is woken.

Cases let a standing service survive process restarts and context replacement.
Signals can resolve an external-dependency blocker or create one follow-up task;
future owners receive the whole current case rather than a forwarded chat
message.

### Manager

The manager is a planner and reconciler. On each invocation it receives bounded pages of current state and unseen events, then retrieves more when a decision requires the full history. It creates a few bounded investigations, combines their findings, and then creates justified implementation or verification tasks. Durable review triggers can invoke it while unrelated workers remain active; reviews are serialized and nearby normal triggers are coalesced.

The manager should be restartable. It must not depend on remembering a previous conversation.

### Workstreams

Workstreams are the executive layer between the mission and individual tasks. Each represents a stable, outcome-oriented line of effort. It records what that line is trying to achieve, how it is going, its forecast window and confidence, and any human decisions blocking its tasks.

A pipeline incident might form three workstreams: diagnose the failure, restore live delivery, and recover the backlog. Each workstream can contain several tasks. Workstreams should remain understandable even as the manager adds, cancels, or replaces low-level tasks.

### Workers

A worker owns one task at a time. The worker receives a lease so two agents do not accidentally own the same work. It reads all new events, performs its bounded work, checkpoints important progress, and completes only with verification evidence.

### Findings and manager reviews

Workers can elevate a source-backed `ROUTINE`, `MATERIAL`, or `URGENT` finding
without creating work. Material and urgent findings request a durable manager
review. The manager incorporates, defers, or dismisses each consequential
finding with a rationale and links any resulting work. Task completion, wait
entry, expired leases, and wait deadlines also request review; ordinary
checkpoints do not.

Manager-review records serialize planning and make responsiveness measurable.
The scheduler gives a due manager review priority over new worker claims while
leaving sound in-flight ownership untouched.

### External waits

An external wait records a task's condition, provider correlation reference,
next check or expected signal, and mandatory deadline. Entering
`WAITING_EXTERNAL` clears the task owner and lease. The task remains
non-terminal, does not satisfy dependencies, and consumes no agent slot after
its harness process exits.

Scheduled reconciliation, an idempotent external signal, or the deadline wakes
the task once. Waking changes eligibility and records why; it never records
success. A fresh owner verifies provider state and may schedule another wait.

### Policy packs

Policy packs add organization- or project-specific workflows without embedding
them in the Swarmkit core. A reviewed pack declares variables, ordered stages,
dependencies, acceptance criteria, fresh-agent constraints, and additional
guidance. Applying it atomically creates ordinary durable tasks, so the workflow
inherits leases, decision propagation, artifacts, reporting, and audit history.

For example, a pull-request policy can require implementation, an
`adversarial-review` skill task, remediation, a second review from a fresh agent
identity, and final green checks. Swarmkit enforces the ordering and identity
separation. The harness provides the actual PR and skill capabilities.

### Decisions and liaison

When the system needs human authority or a business tradeoff, it creates a decision record. The liaison or UI shows that record to you. Your answer is written back to the same record, producing a new version and an event.

The system finds every task affected by the answer. A worker must acknowledge the current decision version before it can report progress or completion. This prevents an answer from being trapped in one agent conversation.

### Briefers

A briefer investigates a question without interrupting workers. It reads the event history, files, logs, and artifacts, then produces a cited memo. Briefers are read-only unless their task explicitly says otherwise.

### Status reporter

Status is a view of the database. The generated board and invariant checker usually provide enough information for a cron job. If a model formats the report, it receives the current canonical state rather than an old conversation transcript.

### Delivery extensions and outbox

Swarmkit can hand a finished report or artifact to email, chat, ticketing, or
another provider without building those providers into the core. It first
copies the content into an immutable, hashed outbox entry. A reviewed extension
then uses either a narrow harness agent with existing skills and authentication,
or a direct command adapter.

The job is durable: it has an idempotency key, lease, attempts, errors, and a
provider receipt. A process exit is not proof of delivery. Only a recorded
provider acknowledgement moves it to `SENT`; ambiguous attempts remain visible
and recoverable.

### Time-bounded facts

Operational observations are stored as facts with a subject, value, source, observation time, and optional expiry. Recording a newer fact for the same subject supersedes the old one. The reconciler marks expired facts automatically, so an agent cannot mistake an hours-old health check for current evidence merely because it remembers the text.

## How an ambiguous objective becomes work

The system uses four phases:

1. `DISCOVERY`: gather independent evidence and locate the problem.
2. `EXECUTION`: make the smallest supported change.
3. `VERIFICATION`: independently prove the mission outcome.
4. `RECOVERY`: repair data, state, or service after the immediate fault is fixed.

The manager initially creates two to four discovery tasks. For a broken pipeline, these might inspect the failure timeline, trace one record, compare recent changes, and quantify the backlog. The tasks are useful independently and do not make competing changes.

When the findings point to one cause, the manager cancels obsolete ideas and creates a coherent implementation task. Afterward, a separate verifier checks the real system rather than trusting the implementation summary.

## Task lifecycle

```text
PROPOSED ──authorized and dependencies done──> READY
READY ──claim with lease──> CLAIMED
CLAIMED ──checkpoint──> RUNNING
RUNNING ──verified result──> DONE
RUNNING ──durable question──> BLOCKED
RUNNING ──external condition and deadline──> WAITING_EXTERNAL
WAITING_EXTERNAL ──check, signal, or deadline──> READY
BLOCKED ──decision resolved──> READY
Any non-terminal task ──manager cancellation──> CANCELLED
```

`PROPOSED` is important. It lets the manager record an idea without spending agent time on it. Only authorized tasks whose dependencies are finished become `READY`.

## Events and inboxes

Every state change produces an ordered event. Each agent has a cursor marking the last event it processed. At the beginning of an invocation, the manager receives the first bounded page of unseen events. It retrieves and acknowledges additional pages before relying on a complete history. A task worker reads unseen mission events plus events for its task, dependencies, decisions, artifacts, and runs. It considers the whole relevant batch before acting.

This changes communication from “react to the latest message” into “reconcile everything that changed since I last looked.”

## Leases

When a worker claims a task, it receives an expiration time and an incremented generation. Checkpoints renew the lease. If the worker disappears, the reconciler returns the task to `READY` after expiration. An old worker cannot checkpoint or complete after its lease has expired.

## What is automatic and what uses a model?

Deterministic code handles:

- task ownership and leases;
- external-wait schedules, idempotent signals, deadlines, and wake fencing;
- dependency readiness;
- event ordering and inbox cursors;
- finding records, dispositions, links, and mission-completion gates;
- coalesced, leased, serialized manager-review triggers;
- responsive capacity-aware scheduling within bounded runs;
- decision propagation and acknowledgment;
- policy validation, task-graph creation, and fresh-agent constraints;
- service/finite mission mode, idempotent cases, immutable intake payloads,
  follow-up signals, and case-state reconciliation;
- extension validation, recipient allowlists, immutable outbox records, leases,
  idempotency, acknowledgements, and delivery audit history;
- generated board state;
- workstream/task relationships and executive report structure;
- invariant checks;
- audit collection.

Models handle:

- choosing useful investigations;
- interpreting evidence;
- proposing and implementing changes;
- recognizing meaningful uncertainty;
- independent verification and briefing;
- invoking harness-provided skills named by trusted policy or delivery guidance.

This division is deliberate. Models make judgments; code enforces bookkeeping.

## When the system stops

The bounded run is an event loop rather than a worker-wave barrier. A scheduling
turn launches one manager review or one worker batch. While child processes are
alive it polls durable events, prioritizes due manager review, and fills newly
free slots without waiting for unrelated workers.

The run loop stops when:

- the mission is complete;
- an open human decision prevents further ready work;
- all unfinished work is waiting for future external conditions;
- no work is ready;
- the configured cycle limit is reached.

Stopping at the cycle limit is a safety boundary, not mission success. Inspect the board, health report, and latest agent output before resuming.

When it stops as `WAITING_EXTERNAL`, it reports the earliest check, earliest
deadline, signal expectations, and any deadline wake needing attention. An
external scheduler resumes the next bounded run; Swarmkit does not remain alive
for hours.

For a service mission, `NO_READY_WORK` is the normal idle state. It does not
complete the mission. An ingress adapter records a new case or signal before
starting another bounded run.

## How to improve it over time

Export an audit archive after every significant mission, including unsuccessful ones. Compare runs for recurring coordination failures:

- tasks created without evidence;
- duplicated or overlapping work;
- long gaps between checkpoints;
- decisions that took too long to reach workers;
- agents acting on stale facts;
- repeated lease expiration;
- failed, repeatedly retried, or unacknowledged external deliveries;
- duplicate intake, missed case signals, or cases reopened without evidence;
- completion claims with weak verification;
- too many manager cycles that create no useful state change.
- slow manager response to consequential findings or completed tasks;
- findings without explicit dispositions or links to resulting work;
- waits repeatedly rescheduled without evidence, duplicate wake signals, or
  deadlines treated as success.

Turn each recurring failure into a CLI invariant, a smaller task schema, a clearer role rule, or a harness-level guard. Prefer enforceable mechanisms over adding more prose to every prompt.

## Runtime safety and recovery (0.7.0)

The [durable runtime contract](RUNTIME_SAFETY.md) documents `pause`, `drain`,
`resume`, `cancel`, `abandon`, `recover`, `why`, and `serve`, along with leased
inboxes, effect reconciliation, task worktrees, resource leases, evidence
contracts, amendments, limits, model escalation, and audit verification.
Use its examples for new integrations. The
[roadmap backlog](ROADMAP_BACKLOG.md) distinguishes shipped slices from remaining
engineering work and owner decisions. Permission enforcement stays with the
harness and tools. Runtime process locking requires a single POSIX host.

## VCS-neutral workspaces (0.7.1)

The target environment may use jj, Git, or an internal checkout system. Swarmkit
records a directory, opaque revision/reference, and provider; only the explicitly
selected Git provider invokes Git. Configure `runner.json` `workspace.provider`
as `command` for a repeatable internal CLI, or use `workspace register` for a
harness-created checkout. The default is manual registration, with no VCS
assumption. See the [workspace adapter contract](RUNTIME_SAFETY.md#isolate-files-and-scarce-resources)
for argv placeholders, JSON receipts, ownership, failure handling, and migration.

## Consistent operator reads

A status snapshot, health check, or explanation uses one SQLite read transaction.
Other processes may commit while it is being assembled; related task, case,
workstream, decision, and run fields still describe the same database version.
Read helpers reuse a caller's existing transaction and never commit or roll back
that caller's pending writes. A report gathers its snapshot, health, and failed
runs in the same read scope.

Entity `list`/`show` commands retain their reconciliation behavior where applicable,
then read one snapshot. They do not regenerate whole-mission boards or reports as
a side effect. Use `board` or `report` to refresh those derived files explicitly.
This keeps an agent's targeted retrieval inexpensive and avoids unrelated writes.

## Published plans and durable operator attention

A manager can reason while workers execute the last committed plan. New task
creations and authorizations are staged against its review, then published with
review completion in one write transaction. Strict review commits are invalidated
by subsequent additions. Negative changes, including cancellation and decision
fencing, act immediately. This separates planning time from dispatch without
using wall-clock timestamps as proof of authorization.

Manager attempts have unique identities and durable retry counters. Backoff and
escalation survive process restarts. A shared attention projection describes
unresolved decisions, and durable scoped transitions can feed versioned opt-in
outbox routes. The database remains authoritative; boards and notification payloads
are views or immutable event snapshots.

Task acceptance revisions preserve identity and history across quiescent changes.
Conditional grants bind named checks, scope, expiry, and explicit waivers to
current decisions and external effects. Permission enforcement and provider
execution remain outside Swarmkit. See [runtime safety](RUNTIME_SAFETY.md),
[responsive orchestration](RESPONSIVE_ORCHESTRATION.md), and
[conditional grants](CONDITIONAL_GRANTS.md) for the operational contracts.
