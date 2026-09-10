# Persistent agent services

Swarmkit supports a persistent logical agent as a durable service, not as one model
conversation that runs forever.

The service keeps a stable mission, operating rules, installed policies,
inbound case queue, decisions, facts, artifacts, and audit history. Each unit of
work is executed in a fresh harness invocation. When no work is ready,
`swarmctl run` exits normally; a scheduler, webhook adapter, or human starts the
next bounded run after recording new input.

```text
provider notification ──> case open ──> policy tasks ──> fresh agents
                               ↑                              │
author response ─────────> case signal ──────────────────────┘
human answer ─────────────> versioned decision
```

This avoids context rot while preserving continuity.

## Platform concepts

### Service mission

Initialize a standing service with `--mode SERVICE`:

```bash
swarmctl --root /work/change-reviewer/.swarm init \
  --mode SERVICE \
  --objective "Independently review submitted engineering changes" \
  --success "Every accepted request reaches a durable, evidence-backed disposition" \
  --constraint "Only the human may authorize approval" \
  --constraint "Never infer approval from silence"
```

A service mission remains `ACTIVE` when its queue is empty. `mission complete`
refuses to terminate it accidentally; deliberate retirement requires
`mission complete --shutdown-service` after all workstreams and tasks are
terminal.

### Case

A case is one durable inbound request: a proposed change, incident, support
ticket, document review, or other unit of service work. It has a provider
source, provider-stable external ID, objective, priority, immutable initial
payload, dedicated workstream, tasks, policy application, signals, decisions,
and result.

`source + external-id` is unique within the service. Replaying the same request
with the same content returns the original case. Reusing the key with different
content is rejected. This is the ingestion idempotency boundary.

Case states are derived from their current work:

| State | Meaning |
|---|---|
| `OPEN` | Recorded but no task or policy is attached yet |
| `ACTIVE` | Work is proposed, ready, or running |
| `WAITING_HUMAN` | A linked human decision, access grant, or safety stop is open |
| `WAITING_EXTERNAL` | A linked external or technical dependency is open |
| `VERIFYING` | Linked work is in verification |
| `DONE` | Linked work reached a verified terminal result |
| `CANCELLED` | The case and remaining work were explicitly cancelled |

### Signal

A signal is an inbound follow-up such as a new revision, author response,
provider status, comment, or retry notification. Signals also use a
`source + external-id` idempotency key and may include an immutable payload.

A signal can:

- simply add current evidence to a case;
- resolve a linked external-dependency decision with `--decision D-ID`; or
- create a ready follow-up task with `--wake` when a terminal or idle case must
  be reconsidered.

Task prompts include their complete current case and signals. Task-specific
inboxes include case and signal events, so follow-ups do not depend on private
agent messages.

## Generic ingress flow

An organization-owned adapter receives a webhook or polls the provider, saves
the untrusted provider payload to a local file, and invokes:

```bash
swarmctl --root /work/change-reviewer/.swarm case open \
  --source review-provider \
  --external-id "project/change/42" \
  --title "Review change 42" \
  --objective "Reach an independent, human-authorized disposition" \
  --payload /work/intake/event-8001.json \
  --metadata repository=project/service \
  --policy human-gated-change-review \
  --var change_ref=https://review.example/42 \
  --var review_skill=adversarial-review \
  --var 'verification_command=python3 -m unittest' \
  --ready \
  --actor review-webhook
```

Then it starts a bounded run:

```bash
swarmctl --root /work/change-reviewer/.swarm run --max-cycles 10
```

The adapter may safely repeat both steps after a timeout. `case open` will not
duplicate the case or policy graph.

Use a reviewed, organization-owned adapter rather than embedding provider
webhook servers and credentials in Swarmkit. The adapter must validate provider
signatures, restrict the mission root, write payloads outside the repository,
and pass them as data. Never interpolate webhook text into a shell command.

## Adopt or replace a case plan

After an intake investigation, apply a reviewed policy with `case apply-policy`.
By default, unfinished intake work must be completed or cancelled first. Repeating
the identical initial request returns its original application. Use
`--idempotency-key` for an explicitly named planning request. The key binds the
reviewed policy definition/guidance, resolved variables, readiness, and replacement
rationale. Changed work under the same key is rejected.

When new evidence makes the current plan obsolete, replace it in one transaction:

```bash
swarmctl case apply-policy C-ID pipeline-repair \
  --var 'goal=Restore delivery and verify backlog recovery' \
  --var 'test_command=repository-approved-check' --ready \
  --replace --idempotency-key incident-42-plan-v2 \
  --reason 'Diagnosis isolated the destination failure'
```

The command creates the new policy graph and retires unfinished case tasks
atomically. Invalid input, exhausted quotas, or a database failure leave the old
plan intact. Completed tasks, old policy snapshots, and cancellation reasons remain
in history. A retry returns `replayed: true` and
`applied_policy_application_id` for that request. The ordinary case
`policy_application_id` always identifies its current plan, which may have changed
since an older request. Retrying an older key never reinstalls an obsolete plan.

Replacement refuses to cancel dependency descendants outside the case. It also
requires old case harnesses to finish or be recovered, and external effects or
checkout creation to be reconciled. A cancelled case cannot receive a new plan.

Open questions and resolved answers are linked to every new task before old work
is retired. Open questions keep gating work; fresh owners must acknowledge current
answers. These links preserve the human context; they do not grant permission for
a different provider action or revision. The harness still checks actual authority.
If a question's scope has changed, revise it explicitly before proceeding.

Applications created by an older release have no new retry record. Inspect them
with `case show`/`policy application`; an unkeyed call will not silently adopt a
legacy application or create a duplicate. General cross-case plan replacement
remains outside this command.

## Human and external waits

When a worker needs human authority, it creates a `human_decision` blocker. The
UI or liaison reads `decision list`, presents the explainer and recommendation,
and writes the answer with `decision resolve`. For machine-enforced downstream
gates, it also records an exact offered option with `--choice approve` or
`--choice withhold`; free-form reasons remain in `--answer`. Every later task owner must
acknowledge the current decision version.

When work is waiting for an author or provider, it creates an
`external_dependency` blocker. The ingress adapter records the response and
resolves that exact blocker:

```bash
swarmctl --root /work/change-reviewer/.swarm case signal C-ID \
  --source review-provider \
  --external-id event-9001 \
  --kind author_response \
  --author author@example.com \
  --body "Revision 7 addresses the requested validation" \
  --payload /work/intake/event-9001.json \
  --decision D-ID \
  --actor review-webhook

swarmctl --root /work/change-reviewer/.swarm run --max-cycles 10
```

Resolving the blocker means “new evidence is available,” not “the author's
claim is true.” The fresh owner must inspect the current revision. If the
response contradicts, weakens, or asks for interpretation of human conditions,
the workflow creates another human decision.

If a completed case receives a materially new revision without an existing
blocker, use `--wake` to create one follow-up task:

```bash
swarmctl --root /work/change-reviewer/.swarm case signal C-ID \
  --source review-provider \
  --external-id event-9002 \
  --kind new_revision \
  --body "Revision 8 uploaded after disposition" \
  --wake \
  --actor review-webhook
```

## Human-gated change-review example

The bundled `human-gated-change-review` policy demonstrates a reusable pattern:

1. A cold reviewer inspects the exact current revision, publishes supported
   findings, and creates a plain-language deep-dive explainer with an
   approve/defer recommendation.
2. A briefing task presents that artifact and records the human's versioned
   approve/withhold decision.
3. An execution task either submits the authorized approval or publishes the
   withholding reasons and waits for an idempotent author-response signal. It
   verifies any claimed fix and returns contradictions to the human.
4. A fresh verifier audits the final disposition against current provider
   state, decisions, signals, and receipts.

This is an example policy, not core review logic. Copy it outside Swarmkit and
adapt the provider actions, named skill, checks, and approval rules to your
organization. The same case/signal primitives support incident responders,
ticket triage, document review, compliance intake, and other standing agents.

## Scheduling and context rotation

Swarmkit is deliberately not a webhook server or forever-running daemon. Use
the harness's scheduler, a system service, or a provider webhook adapter to:

1. record new cases or signals;
2. invoke `run --max-cycles N`;
3. inspect its terminal state; and
4. invoke another bounded run only when policy permits.

Inside each bounded run, responsive orchestration can review completed work or
material findings while unrelated harness processes remain active. Policy tasks
waiting on long provider operations should use `task wait-external`; provider
callbacks use `wait signal`. This releases ownership and capacity without
misusing an `external_dependency` decision. The generic scheduling and wake
contract is in [Responsive orchestration](RESPONSIVE_ORCHESTRATION.md).

Every dispatch must start a new harness session. A stable manager `agent_id`
may retain an event cursor, but it must not resume a chat. Workers should use a
new identity per task attempt. Durable checkpoints and case state make agent
replacement normal rather than exceptional.

## What persists

Persist mission constraints, reviewed policy packs, case evidence, decisions,
and sourced facts. Mutable provider facts need observation timestamps and
expiry. Do not persist free-form “memory” that silently becomes authority.

Provider-specific actions remain outside core:

- inbound adapters validate webhooks and call `case open` or `case signal`;
- harness skills or provider adapters read and comment on changes;
- delivery extensions push reports and notifications;
- a pull-based UI reads `status`, `case show`, and generated Markdown, and
  writes mutations only through the CLI.

For high-risk actions such as approval or merge, the provider adapter should
require the expected structured option immediately before execution:

```bash
swarmctl --root /work/change-reviewer/.swarm decision require-choice D-ID \
  --choice approve
```

The command fails unless the decision is resolved and its current structured
choice exactly matches. Do not expose an ungated approval or merge capability to
the agent. Policy guidance and model behavior are not a substitute for
provider-side authorization controls.

## Operations and audit

Use these commands for a pull-based operational view:

```bash
swarmctl --root /work/change-reviewer/.swarm case list
swarmctl --root /work/change-reviewer/.swarm case list --status WAITING_HUMAN
swarmctl --root /work/change-reviewer/.swarm case show C-ID
swarmctl --root /work/change-reviewer/.swarm report
swarmctl --root /work/change-reviewer/.swarm doctor
```

Audit exports include case and signal records, immutable intake payloads,
decisions and acknowledgements, policy snapshots, prompts, provider receipts,
and execution logs. Inspect the archive for confidential code and comments
before sharing it.

## Runtime safety and recovery (0.7.0)

The [durable runtime contract](RUNTIME_SAFETY.md) documents `pause`, `drain`,
`resume`, `cancel`, `abandon`, `recover`, `why`, and `serve`, along with leased
inboxes, effect reconciliation, task worktrees, resource leases, evidence
contracts, amendments, limits, model escalation, and audit verification.
Use its examples for new integrations. The
[roadmap backlog](ROADMAP_BACKLOG.md) distinguishes shipped slices from remaining
engineering work and owner decisions. Permission enforcement stays with the
harness and tools. Runtime process locking requires a single POSIX host.

## Completion, follow-ups, and cancellation

`DONE` means that the current case has no unfinished linked tasks. Inspect
`completion_outcome` to distinguish `SUCCEEDED`, `PARTIAL` (a mixture of completed
and cancelled tasks), and `CANCELLED` (no linked task delivered a result). The
linked workstream carries the same result, and operator reports display it. These
are conservative summaries of linked task history, not proof of mission criteria.

Only `case cancel` permanently closes a request to new work. Cancelling an obsolete
intake task permits a replacement policy or a later follow-up; it does not silently
turn into permanent case cancellation. Explicit case cancellation also cancels
dependency descendants outside the case. Questions with no remaining active
affected tasks are withdrawn; shared questions remain open for other work.

New follow-up work clears the old completion summary and timestamp. Repeating an
already-recorded task link does not reopen a completed case. A late reply to a
withdrawn question is retained as a signal without resolving or reopening it.

### Follow-up identity

Each signal that creates follow-up work has a durable signal-to-task relationship.
Retrying the same signal returns the same task even if its description changes or
the case is subsequently cancelled. Mentioning a signal in another task's prose
does not count as handling it. New wakeups on explicitly cancelled cases remain
rejected. Schema 9 reconstructs existing links from structured `CASE_WOKEN` events.

### Atomic intake and inquiries

Case creation, policy/task attachment, and their events commit together. Signal
recording and its decision/wakeup also form one transaction. A changed payload
between request fingerprinting and copying is rejected. Failed intake commands
remove only the snapshots they created, preserving earlier case payloads.

Asking a new question about a completed case reopens it only if its briefing task
and links can be created successfully. New work clears the old completion summary.
An identical case-open retry returns the existing case even after mission
cancellation; it does not create new work or undo cancellation.

SQLite and files cannot share a crash-atomic transaction. A killed process or a
Python caller rolling back a larger outer transaction may leave unregistered
payload snapshots. Audits include only intake files referenced by the frozen
database, and do not delete live files or checkouts automatically.

Human-attention transitions and optional notification cursors survive idle periods
and restart. A case can need human attention while other cases run. Use explicit
[event routes](EXTENSIONS.md#event-notifications) for delivery and preserve the
normal provider reconciliation rules. `serve` exposes polling exhaustion and a
next action; an external supervisor still owns later wakeups, including scheduled
manager retries. An escalated review requires deliberate repair and reset.

## Cases with delivery commitments

A case containing open [delivery commitments](DELIVERY_COMMITMENTS.md) cannot
become DONE solely because its tasks are terminal. It remains waiting until
responsibility is satisfied or explicitly cancelled. Case details expose the
records and summary counts; cancellation disposes the case's commitments with
the same audited reason while preserving uncertain effects. Producer/follow-up
links remain within the same case/workstream. Use the author-to-merge pack for
authoring services; it is separate from the reviewer-service example above.
