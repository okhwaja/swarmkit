# Swarmkit user manual

This manual is for the person who assigns a mission, follows its progress, answers questions, and asks for investigations. You do not need to understand the internal event database.

In the commands below, replace `/work/my-run/.swarm` with your mission's state directory. Commands return IDs such as `WS-...`, `T-...`, and `D-...`; copy those IDs into later commands.

## Common journeys

| You want to… | What you do | What happens next |
|---|---|---|
| Connect Swarmkit to a harness on a new machine | Give the setup agent `SETUP_AGENT.md`, then require its setup report and audit ZIP | The agent discovers local CLI details but must pass Swarmkit's fixed integration gates |
| Start an ambiguous objective | Run `swarmctl init`, configure `runner.json`, then run `swarmctl run` | The manager creates bounded discovery work and progressively forms the plan |
| Get the executive view | Run `swarmctl report` and open `views/STATUS.md` | You see major workstreams, outcomes, progress, forecast ranges, confidence, and needs from you |
| Receive the executive view by email | Install an allowlisted delivery extension, enqueue the report, and dispatch the returned job | Swarmkit snapshots the report and tracks the send until the provider returns a receipt |
| Inspect delivery problems | Run `swarmctl delivery list` or open the report/board | You see pending, claimed, failed, sent, and cancelled jobs with attempt history |
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

The command stops when the mission finishes, needs a human decision, has no ready work, or reaches the cycle limit. A stopped command does not mean the mission failed or completed; inspect the report.

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
- Are there failed agents or coordination problems?

An unknown forecast is valid during early discovery. Forecasts are required to include a basis when the manager records a date.

For a scheduled email, use the delivery outbox journey below. Your scheduler
chooses the interval. Swarmkit generates and snapshots the content; a narrow
harness agent or reviewed command adapter performs the send with credentials
that stay outside Swarmkit.

For a pull-based UI, render `swarmctl status` JSON or serve the two generated Markdown files from an authenticated internal endpoint.

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

The archive includes `REVIEW_ME.md`. Give the entire ZIP to a reviewer or analysis model and ask it to identify stale facts, duplicated work, poor decomposition, decision delays, context-rotation failures, weak verification, forecast misses, or excessive manager churn.

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
| Repair stale scheduling state | `reconcile` |
| Review the orchestration itself | `export` |

Changing the mission's objective or issuing an immediate stop directive is not yet a first-class command. Stop unattended cycles before making such a change, record the direction through your controlled operator procedure, and do not disguise it as a briefing inquiry.
