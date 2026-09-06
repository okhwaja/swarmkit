# System explainer

## What problem does this solve?

Suppose you tell a team of agents, “Our data pipeline is broken. Find out why and fix it.” You do not yet know whether the problem is in the source, queue, credentials, application code, destination, or monitoring. That means you cannot provide a detailed work plan.

The system lets you provide the outcome and safety boundaries instead. A manager agent investigates the problem in small steps, creates work when evidence supports it, and changes the plan as new information arrives.

The hard part is coordination. Agent conversations are temporary and can become stale. If one agent privately tells another about a decision, other workers may never learn it. Swarmkit therefore keeps important information in a shared database and records every meaningful change in an ordered event log.

## The pieces

### Mission

The mission is the result you want. It contains an objective, success conditions, constraints, phase, and completion evidence. It does not need to contain a detailed technical plan.

### Manager

The manager is a planner and reconciler. On each invocation it reads the complete current state and all events it has not seen. It creates a few bounded investigations, combines their findings, and then creates justified implementation or verification tasks.

The manager should be restartable. It must not depend on remembering a previous conversation.

### Workstreams

Workstreams are the executive layer between the mission and individual tasks. Each represents a stable, outcome-oriented line of effort. It records what that line is trying to achieve, how it is going, its forecast window and confidence, and any human decisions blocking its tasks.

A pipeline incident might form three workstreams: diagnose the failure, restore live delivery, and recover the backlog. Each workstream can contain several tasks. Workstreams should remain understandable even as the manager adds, cancels, or replaces low-level tasks.

### Workers

A worker owns one task at a time. The worker receives a lease so two agents do not accidentally own the same work. It reads all new events, performs its bounded work, checkpoints important progress, and completes only with verification evidence.

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
BLOCKED ──decision resolved──> READY
Any non-terminal task ──manager cancellation──> CANCELLED
```

`PROPOSED` is important. It lets the manager record an idea without spending agent time on it. Only authorized tasks whose dependencies are finished become `READY`.

## Events and inboxes

Every state change produces an ordered event. Each agent has a cursor marking the last event it processed. At the beginning of an invocation, the manager reads every unseen event. A task worker reads unseen mission events plus events for its task, dependencies, decisions, artifacts, and runs. It considers the whole relevant batch before acting.

This changes communication from “react to the latest message” into “reconcile everything that changed since I last looked.”

## Leases

When a worker claims a task, it receives an expiration time and an incremented generation. Checkpoints renew the lease. If the worker disappears, the reconciler returns the task to `READY` after expiration. An old worker cannot checkpoint or complete after its lease has expired.

## What is automatic and what uses a model?

Deterministic code handles:

- task ownership and leases;
- dependency readiness;
- event ordering and inbox cursors;
- decision propagation and acknowledgment;
- policy validation, task-graph creation, and fresh-agent constraints;
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
- independent verification and briefing.
- invoking harness-provided skills named by trusted policy or delivery guidance.

This division is deliberate. Models make judgments; code enforces bookkeeping.

## When the system stops

The run loop stops when:

- the mission is complete;
- an open human decision prevents further ready work;
- no work is ready;
- the configured cycle limit is reached.

Stopping at the cycle limit is a safety boundary, not mission success. Inspect the board, health report, and latest agent output before resuming.

## How to improve it over time

Export an audit archive after every significant mission, including unsuccessful ones. Compare runs for recurring coordination failures:

- tasks created without evidence;
- duplicated or overlapping work;
- long gaps between checkpoints;
- decisions that took too long to reach workers;
- agents acting on stale facts;
- repeated lease expiration;
- failed, repeatedly retried, or unacknowledged external deliveries;
- completion claims with weak verification;
- too many manager cycles that create no useful state change.

Turn each recurring failure into a CLI invariant, a smaller task schema, a clearer role rule, or a harness-level guard. Prefer enforceable mechanisms over adding more prose to every prompt.
