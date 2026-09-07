# Swarmkit user manual

This manual is for the person who assigns a mission, follows its progress, answers questions, and asks for investigations. You do not need to understand the internal event database.

In the commands below, replace `/work/my-run/.swarm` with your mission's state directory. Commands return IDs such as `C-...`, `WS-...`, `T-...`, and `D-...`; copy those IDs into later commands.

## First look

Run `python3 swarmctl.py demo` from the package directory for a complete synthetic
pipeline-repair example. It creates a new `swarm-demo/` directory, report, and audit
ZIP, without invoking an agent or provider. It does not use `SWARM_ROOT`; an explicit
`--root` selects a different new demo mission. Existing demo state/output is preserved.

For any mission, `swarmctl --root /work/my-run/.swarm status --brief` gives the
objective, lifecycle state, task counts, outstanding questions, and a next action.
Use `decision show D-ID` to inspect one question. The existing `status` command
continues to return the full JSON snapshot.

Initialization publishes a complete database under a process lock. If schema or
initial state creation fails, you can retry `init`; no partial canonical database
is left behind. Existing `runner.json` settings are preserved. A completed mission
cannot be overwritten by another `init`.

## Common journeys

| You want to… | What you do | What happens next |
|---|---|---|
| Connect Swarmkit to a harness on a new machine | Give the setup agent `SETUP_AGENT.md`, then require its setup report and audit ZIP | The agent discovers local CLI details but must pass Swarmkit's fixed integration gates |
| Start an ambiguous objective | Run `swarmctl init`, configure `runner.json`, then run `swarmctl run` | The manager creates bounded discovery work and progressively forms the plan |
| Follow an evolving mission | Keep one bounded `run` active while agents work | Completed tasks and consequential findings can trigger a serialized manager review while unrelated work continues |
| Elevate a consequential discovery | The owning worker runs `finding raise` with evidence, impact, significance, and a bounded recommendation | Material and urgent findings prompt manager review but do not authorize worker scope expansion |
| Triage an elevated finding | The manager runs `finding disposition` with incorporated, deferred, or dismissed and a rationale | The disposition and any resulting task/workstream links remain auditable |
| Wait on CI, a pipeline, or another provider | The worker runs `task wait-external` and exits | The task releases its owner and slot until a scheduled check, external signal, or deadline wakes it for verification |
| Wake a task from a provider callback | A trusted adapter runs `wait signal` with a stable provider event ID | Repeated signals do not create duplicate eligibility; a fresh worker checks actual provider state |
| Create a persistent logical agent | Initialize with `--mode SERVICE`, install reviewed policies, and connect an ingress adapter | The service remains available while idle, but each case runs in fresh model sessions |
| Submit work to a persistent agent | Run `case open` with a provider-stable source/external ID | Duplicate notifications collapse into one durable case and workstream |
| Record an author reply or new revision | Run `case signal`, optionally with `--decision` or `--wake` | The response reaches every future owner and resumes or creates only the intended work |
| Inspect a standing agent's queue | Run `case list`, `report`, or open the generated board | You see active cases and those waiting for human or external input |
| Get the executive view | Run `swarmctl report` and open `views/STATUS.md` | You see major workstreams, outcomes, progress, forecast ranges, confidence, and needs from you |
| Receive the executive view by email | Install an allowlisted delivery extension, enqueue the report, and dispatch the returned job | Swarmkit snapshots the report and tracks the send until the provider returns a receipt |
| Inspect delivery problems | Run `swarmctl delivery list` or open the report/board | You see pending, claimed, failed, unknown, sent, and cancelled jobs with attempt history |
| Inspect all execution detail | Run `swarmctl board` and open `views/BOARD.md` | You see every task, workstream relationship, decision, fact, and recent event |
| Inspect one workstream | Run `swarmctl workstream show WS-ID` | You get its narrative, forecast, tasks, and open decisions as JSON |
| Apply an organization-specific workflow | Install a reviewed policy pack, then run `swarmctl policy apply` | Swarmkit creates and enforces the pack's ordered task graph and guidance |
| Require two adversarial PR reviews | Apply the `pr-adversarial-review` policy with the change goal and test command | The PR moves through implementation, review, remediation, fresh review, and final-green stages |
| Ask “what happened to X?” | Run `swarmctl ask --question ... --workstream WS-ID`, then resume `run` | A read-only briefer investigates without interrupting active workers |
| Answer something blocking the swarm | Run `swarmctl decision list`, then `decision resolve` | Every affected task becomes eligible to resume and must acknowledge the answer |
| Correct an earlier answer | Run `swarmctl decision revise` | Old acknowledgments become stale and active owners are fenced |
| Check whether an agent stalled | Run `swarmctl doctor` and inspect the executive report | Expired leases, failed runs, and incomplete exits are visible; eligible tasks are requeued |
| Pause unattended orchestration | Let the bounded `run` command exit or stop launching new cycles | Durable state remains intact; start another bounded run when ready |
| Review or improve a completed run | Run `swarmctl export --include-artifacts` | You receive an audit ZIP with state, events, prompts, outputs, metrics, hashes, and artifacts |

## Journey 0: connect a new harness machine

Copy the complete package to the machine. Assign [SETUP_AGENT.md](../SETUP_AGENT.md)
to an agent that can inspect the installed third-party harness and work in a
disposable local directory. Require the agent to return `SETUP_REPORT.md` and a
sandbox audit ZIP.

The setup agent is responsible for discovering the harness's executable,
non-interactive syntax, authentication prerequisites, workspace selection,
fresh-session option, and exit behavior. The playbook fixes the architecture and
acceptance tests so those parts are not left to inference.

Before any live agent test, require:

```bash
swarmctl --root /work/setup-sandbox/.swarm setup-check
```

An `ok: true` result means the static adapter checks passed. It does not mean the
live integration is complete; the playbook also requires manager persistence,
worker persistence, fresh-context, decision propagation, and final audit tests.

## Journey 1: start a mission

Describe the outcome, evidence of success, and boundaries. You do not need to invent technical workstreams or tasks.

```bash
swarmctl --root /work/my-run/.swarm init \
  --objective "Restore reliable delivery through the customer data pipeline" \
  --success "New records reach the destination" \
  --success "The backlog is accounted for without loss or duplication" \
  --success "The failure mode is monitored" \
  --constraint "Ask before destructive production changes" \
  --constraint "Preserve customer data"
```

Edit `/work/my-run/.swarm/runner.json` with your harness command. Test it without launching an agent:

```bash
swarmctl --root /work/my-run/.swarm setup-check

swarmctl --root /work/my-run/.swarm dispatch \
  --role manager --agent manager --dry-run
```

Then run a bounded number of manager and worker cycles:

```bash
swarmctl --root /work/my-run/.swarm run --max-cycles 20
```

The command stops when the mission finishes, needs a human decision, is waiting
for future external conditions, has no ready work, or reaches the cycle limit.
A stopped command does not mean the mission failed or completed; inspect the
report. `WAITING_EXTERNAL` includes the earliest check and deadline for an
external scheduler.

## Journey: react to work while other agents continue

Keep the bounded `run` command alive while its launched harness processes are
working. It watches durable state at the configured `scheduler_poll_seconds`.
When a short task completes, its result requests manager review even if an
unrelated long task remains active. The manager sees the complete batch of
nearby changes, updates the plan, and the next scheduling turn fills the freed
slot.

Configure the responsiveness and coalescing interval in `runner.json`:

```json
{
  "max_parallel": 3,
  "scheduler_poll_seconds": 1,
  "manager_review_debounce_seconds": 1
}
```

`max_parallel` counts live manager and worker harness processes. Frequent
worker checkpoints do not wake the manager. A material or urgent finding does.

## Journey: elevate and triage a new finding

The worker that owns a task records a discovery that may change the plan:

```bash
swarmctl --root /work/my-run/.swarm finding raise \
  --task T-ID \
  --agent worker-ID \
  --significance MATERIAL \
  --summary "Retries can create duplicate records" \
  --evidence "log:event-1042" \
  --evidence "src/retry.py:88" \
  --impact "A backlog replay may violate the no-duplication outcome" \
  --recommendation "Run one bounded replay-safety investigation"
```

Use `ROUTINE` for useful context, `MATERIAL` when tasks or workstreams may need
to change, and `URGENT` for immediate safety, security, data-loss, or mission
risk. The worker remains inside its original assignment. If current activity is
unsafe, it also creates the appropriate safety blocker.

The manager inspects open findings and records a disposition:

```bash
swarmctl --root /work/my-run/.swarm finding disposition FND-ID \
  --status INCORPORATED \
  --rationale "Replay correctness is on the mission's critical path" \
  --task T-FOLLOWUP \
  --workstream WS-REPLAY \
  --actor manager
```

The other choices are `DEFERRED` and `DISMISSED`. All require a rationale.
Material and urgent findings must be dispositioned before a finite mission can
complete.

## Journey: wait for an external operation without holding an agent

After starting or observing a long provider operation, the worker records the
condition and exits:

```bash
swarmctl --root /work/my-run/.swarm task wait-external T-ID \
  --agent worker-ID \
  --condition "Pipeline job reaches a terminal state" \
  --external-ref provider-job-123 \
  --next-check-at 2030-01-01T00:15:00Z \
  --signal-expected \
  --deadline 2030-01-01T04:00:00Z
```

The deadline is mandatory, and the wait needs a next check or expected signal.
The task becomes `WAITING_EXTERNAL`, clears its owner and lease, and does not
satisfy dependent tasks. The still-running harness process counts against
capacity until it exits.

At the scheduled time, `run` or `reconcile` wakes the task. A provider callback
can wake it sooner:

```bash
swarmctl --root /work/my-run/.swarm wait signal W-ID \
  --source pipeline-provider \
  --external-id callback-9001 \
  --note "Provider reports completion" \
  --actor pipeline-webhook
```

The source and external ID make callbacks idempotent. The fresh worker must
query the provider. If the operation remains active, it records another wait;
if the deadline fired, the report calls attention to the miss without claiming
success. Full semantics are in
[Responsive orchestration](RESPONSIVE_ORCHESTRATION.md).

## Journey: create a persistent review agent

Create a service mission rather than keeping one model conversation alive:

```bash
swarmctl --root /work/change-reviewer/.swarm init \
  --mode SERVICE \
  --objective "Independently review submitted engineering changes" \
  --success "Every request reaches an evidence-backed disposition" \
  --constraint "Only I may authorize approval"
```

Install a reviewed copy of the example workflow:

```bash
swarmctl --root /work/change-reviewer/.swarm policy install \
  /opt/company/swarmkit-policies/human-gated-change-review \
  --actor human
```

When you or a provider notification submits a change:

```bash
swarmctl --root /work/change-reviewer/.swarm case open \
  --source review-provider \
  --external-id project/change/42 \
  --title "Review change 42" \
  --objective "Reach an independent, human-authorized disposition" \
  --payload /work/intake/event-8001.json \
  --policy human-gated-change-review \
  --var change_ref=https://review.example/42 \
  --var review_skill=adversarial-review \
  --var 'verification_command=python3 -m unittest' \
  --ready

swarmctl --root /work/change-reviewer/.swarm run --max-cycles 10
```

The example policy creates a cold review and digestible explainer, asks you for
an approve/withhold decision, carries out only the authority you grant, waits
durably for requested changes, and uses a fresh verifier for the final
disposition.

When answering that gate, select one of the offered options as well as giving
your reasons:

```bash
swarmctl --root /work/change-reviewer/.swarm decision resolve D-ID \
  --choice withhold \
  --answer "Withhold until the retry path has a concurrency test"
```

For approval and similarly high-risk actions, configure the provider adapter to
require `decision require-choice D-ID --choice approve`; do not give the review
agent an ungated approval capability.

If approval is withheld, inspect the case to find the open external blocker:

```bash
swarmctl --root /work/change-reviewer/.swarm case show C-ID
```

An author response is recorded by the ingress adapter and linked to that
blocker:

```bash
swarmctl --root /work/change-reviewer/.swarm case signal C-ID \
  --source review-provider \
  --external-id event-9001 \
  --kind author_response \
  --body "Revision 7 addresses the requested change" \
  --decision D-ID
```

The next fresh owner must verify the claim. Contradictions or requests to
reinterpret your conditions return to you as a new human decision. A new
revision after completion can use `case signal --wake` to create one follow-up
task.

Your webhook, polling, or notification adapter stays outside Swarmkit. It owns
provider signature verification and authentication; Swarmkit owns idempotent
intake, state, and auditability. See [Persistent services](PERSISTENT_SERVICES.md)
for the complete setup and safety contract.

## Journey 2: get an executive update

```bash
swarmctl --root /work/my-run/.swarm report
```

Open `/work/my-run/.swarm/views/STATUS.md`. It answers:

- What major workstreams exist?
- What is each trying to achieve?
- How is each going?
- What is its expected timing and forecast confidence?
- What needs a decision or access from me?
- What is waiting externally, and what check, signal, or deadline resumes it?
- Which material or urgent findings still need manager disposition?
- Are there failed agents or coordination problems?

An unknown forecast is valid during early discovery. Forecasts are required to include a basis when the manager records a date.

For a scheduled email, use the delivery outbox journey below. Your scheduler
chooses the interval. Swarmkit generates and snapshots the content; a narrow
harness agent or reviewed command adapter performs the send with credentials
that stay outside Swarmkit.

For a pull-based UI, render `swarmctl status` JSON or serve the two generated Markdown files from an authenticated internal endpoint.

Status, health, and related entity fields are read from one database snapshot.
Entity `list`/`show` commands do not regenerate the full mission's Markdown files;
use `board` or `report` to refresh those files explicitly. Brief status also
identifies pending checkout recovery before suggesting another worker run.

## Journey: deliver a report through an extension

Start from the bundled example. Copy it, replace its recipient allowlist, and
review its guidance before installation:

```bash
swarmctl extension validate /opt/company/swarmkit-extensions/status-email

swarmctl --root /work/my-run/.swarm extension install \
  /opt/company/swarmkit-extensions/status-email \
  --actor human
```

Create one immutable job for one intended report window:

```bash
swarmctl --root /work/my-run/.swarm delivery enqueue-report \
  --extension harness-email-example \
  --channel email \
  --subject "Pipeline recovery status" \
  --recipient leader@example.com \
  --idempotency-key "pipeline-status-2026-09-05T2200Z" \
  --actor status-scheduler
```

Dispatch the returned ID through the extension:

```bash
swarmctl --root /work/my-run/.swarm delivery dispatch N-ID \
  --agent status-emailer
```

Try `--dry-run` first to inspect the exact prompt, envelope, and invocation. A
job becomes `SENT` only after the agent or adapter records a provider receipt.
If it becomes `FAILED`, inspect it and make retry an explicit decision:

```bash
swarmctl --root /work/my-run/.swarm delivery show N-ID
swarmctl --root /work/my-run/.swarm delivery retry N-ID --actor human
```

Reusing the same idempotency key with the same payload returns the existing job;
reusing it with different content or recipients is rejected. See
[Extensions](EXTENSIONS.md) for scheduler, command-adapter, allowlist, and
security details.

## Journey 3: inspect a workstream

List workstreams:

```bash
swarmctl --root /work/my-run/.swarm workstream list
```

Inspect one:

```bash
swarmctl --root /work/my-run/.swarm workstream show WS-ID
```

A workstream is broader and more stable than a task. For example, “recover and validate the backlog” may contain separate tasks for measuring backlog size, making replay idempotent, executing replay, and validating destination counts.

Workstream statuses mean:

| Status | Meaning |
|---|---|
| `PLANNED` | The outcome is known, but work has not started |
| `ACTIVE` | Work is progressing |
| `BLOCKED` | The outcome cannot progress until a dependency or decision clears |
| `VERIFYING` | Implementation is complete and evidence is being checked |
| `DONE` | The intended outcome is verified and linked tasks are terminal |
| `CANCELLED` | Evidence or changed priorities made the workstream unnecessary |

To stop an obsolete workstream, supply the reason as its summary:

```bash
swarmctl --root /work/my-run/.swarm workstream update WS-ID \
  --status CANCELLED --summary 'Replaced by the verified recovery approach'
```

Cancellation retires its unfinished tasks and their unfinished dependents,
including dependents in other workstreams. Completed results remain intact.
Active attempts lose ownership; uncertain provider actions remain visible for
reconciliation. This does not kill harnesses or undo external actions. For a
case-owned workstream, use `case cancel CASE-ID --reason '...'` so the case and
its workstream close together. Other workstream states describe progress; they
do not pause or resume workers.

## Journey: apply a reusable workflow policy

Use policy packs for organization- or project-specific best practices that have
an observable sequence. Packs live outside the Swarmkit core. An operator
reviews and installs them; managers apply installed packs when their
`when_to_use` description matches the work.

Validate a pack before it can affect a mission:

```bash
swarmctl policy validate /opt/company/swarmkit-policies/pr-adversarial-review
```

Install it into this mission:

```bash
swarmctl --root /work/my-run/.swarm policy install \
  /opt/company/swarmkit-policies/pr-adversarial-review \
  --actor human
```

Apply it to the relevant workstream:

```bash
swarmctl --root /work/my-run/.swarm policy apply \
  pr-adversarial-review \
  --workstream WS-ID \
  --var 'goal=prevent duplicate replay records' \
  --var 'test_command=python3 -m unittest' \
  --ready
```

This policy creates five dependency-ordered tasks:

1. Implement the change, run tests, and open the PR.
2. In a different agent invocation, run the `adversarial-review` skill and
   register its findings as an artifact.
3. Remediate supported findings and restore passing tests.
4. In a fresh agent invocation, run `adversarial-review` again without inheriting
   the first review's conclusion.
5. Resolve remaining findings and leave the PR and required checks green.

Inspect progress with:

```bash
swarmctl --root /work/my-run/.swarm policy applications
swarmctl --root /work/my-run/.swarm policy application P-ID
```

Swarmkit prevents the first review from using the implementer's agent identity
and prevents the second review from using the first reviewer's or remediator's
identity. Your harness must also honor the fresh-session contract established
during setup. If the named skill is unavailable, the agent should create a
blocker rather than claiming it performed an equivalent review.

See [Policy packs](POLICY_PACKS.md) for authoring, versioning, and trust rules.

## Journey 4: ask a question without interrupting workers

Use `ask` for explanation or investigation:

```bash
swarmctl --root /work/my-run/.swarm ask \
  --workstream WS-ID \
  --question "Why does backlog replay require deduplication, and what evidence supports that conclusion?"
```

The command returns an inquiry task ID. Resume the orchestrator:

```bash
swarmctl --root /work/my-run/.swarm run --max-cycles 5
```

Retrieve the answer and its artifact paths:

```bash
swarmctl --root /work/my-run/.swarm task show T-INQUIRY-ID
```

The briefer reads durable evidence and produces a cited artifact. It should not message or interrupt workers for a recap.

Use this journey for questions such as:

- What happened to this workstream?
- Why did the forecast change?
- Why was an earlier approach rejected?
- What evidence supports the diagnosis?
- What are the risks of a proposed option?

Do not use an inquiry to change priorities or authorize a risky action. Those are directions or decisions, not research questions.

## Journey 5: answer a blocking question

List decisions:

```bash
swarmctl --root /work/my-run/.swarm decision list
```

Resolve the relevant open decision:

```bash
swarmctl --root /work/my-run/.swarm decision resolve D-ID \
  --answer "Pause ingestion for the controlled repair window" \
  --actor human
```

If the previous run stopped while waiting for you, start another bounded run. Do not separately send the answer to a worker. The decision event and acknowledgment rules perform propagation.

If you later correct the answer:

```bash
swarmctl --root /work/my-run/.swarm decision revise D-ID \
  --answer "Pause ingestion, but limit the window to ten minutes" \
  --actor human
```

The revision creates a new version. Affected work must acknowledge the new version before reporting progress or completion.

## Journey 6: inspect detailed state

Generate the complete board:

```bash
swarmctl --root /work/my-run/.swarm board
```

Open `/work/my-run/.swarm/views/BOARD.md`. Use this when you need task-level detail beyond the executive report.

For machine-readable state:

```bash
swarmctl --root /work/my-run/.swarm status
```

For invariant and coordination problems:

```bash
swarmctl --root /work/my-run/.swarm doctor
```

`doctor` reads state without reconciling or repairing it. It returns structured
problems and a nonzero exit code for integrity errors, including malformed stored
timestamps/JSON and missing evidence files. Duplicate active titles are compared
within a workstream; repeated workflow titles in independent cases are expected.
If a cancelled workstream from an older release still contains unfinished tasks,
inspect it and explicitly cancel that work with a recorded reason.


## Journey 7: recover from a stale or failed agent

Normally no manual action is needed. Agent subprocesses that exit without completing return their task to `READY`. Expired leases are also requeued.

Run reconciliation explicitly if the scheduler has been stopped:

```bash
swarmctl --root /work/my-run/.swarm reconcile
```

Then inspect `report` and resume `run`. A replacement receives current task state and relevant events instead of relying on the previous model conversation.

## Journey 8: export a run for review

```bash
swarmctl --root /work/my-run/.swarm export \
  --output /work/exports/pipeline-run.zip \
  --include-artifacts
```

The archive includes `REVIEW_ME.md`. Give the entire ZIP to a reviewer or analysis model and ask it to identify stale facts, duplicated work, poor decomposition, decision delays, context-rotation failures, weak verification, forecast misses, or excessive manager churn. For a service mission, `cases.json` contains complete case and signal histories while `snapshot.json` stays compact.

Prompts, captured output, and artifacts may contain confidential data. Inspect the ZIP before sharing it outside your trusted environment.

## Manager-only workstream operations

Most users should let the manager maintain workstreams. These commands are useful for debugging or manual correction.

Create a workstream:

```bash
swarmctl --root /work/my-run/.swarm workstream add \
  --name "Recover the backlog" \
  --outcome "Replay and verify every recoverable record without duplication" \
  --status ACTIVE
```

Update its narrative and forecast:

```bash
swarmctl --root /work/my-run/.swarm workstream update WS-ID \
  --summary "Replay safety verified; controlled replay remains" \
  --forecast-earliest "2026-09-06T18:00:00Z" \
  --forecast-latest "2026-09-06T21:00:00Z" \
  --forecast-confidence medium \
  --forecast-basis "Validation passed; duration range comes from measured replay throughput"
```

Link an existing task:

```bash
swarmctl --root /work/my-run/.swarm workstream link-task WS-ID --task T-ID
```

Marking a workstream `DONE` is rejected while any linked task remains non-terminal. A mission with workstreams cannot complete until all of them are `DONE` or `CANCELLED`.

## Choosing the right interaction

| Your intent | Use |
|---|---|
| Understand current progress | Executive `report` |
| Inspect implementation details | `board`, `status`, or `task show` |
| Ask for an explanation | `ask` briefing inquiry |
| Answer a question from the swarm | `decision resolve` |
| Correct your answer | `decision revise` |
| Inspect or triage consequential evidence | `finding list`, `finding show`, or `finding disposition` |
| Inspect or wake an external wait | `wait list`, `wait show`, or `wait signal` |
| Repair stale scheduling state | `reconcile` |
| Review the orchestration itself | `export` |
| Inspect or submit standing-service work | `case list`, `case open`, or `case signal` |

Changing the mission's objective or issuing an immediate stop directive is not yet a first-class command. Stop unattended cycles before making such a change, record the direction through your controlled operator procedure, and do not disguise it as a briefing inquiry.

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

Questions and answers must contain actual text. Cancelling all work affected by
an open question withdraws it; a withdrawn decision cannot be linked to new work.
Ask a new question when the scope requires a new answer. Historical links remain
available for audit, and repeated existing links do not change state.
