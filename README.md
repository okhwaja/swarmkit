# Swarmkit

Swarmkit is a small coordination layer for giving ambiguous objectives to a group of agents. It does not contain an AI model and does not depend on a particular agent product. Your existing harness launches the agents; Swarmkit gives those agents a shared state machine, durable inboxes, leases, decisions, generated status views, and a complete audit export.

The package uses Python's standard library and SQLite. Copy the Swarmkit directory to the machine where the work happens.

To create a portable ZIP:

```bash
python3 scripts/package.py
```

This writes `dist/swarmkit-0.3.0.zip` with the CLI, guidance, documentation, examples, policy packs, and tests.

If another agent will connect Swarmkit to the harness on the destination
machine, give that agent [SETUP_AGENT.md](SETUP_AGENT.md) as its assignment.
That playbook separates machine-specific discovery from mandatory integration
behavior and includes live acceptance tests. Do not rely on the setup agent to
reverse-engineer the contract from `swarmctl.py`.

## The basic idea

An agent conversation is temporary. The database is permanent. Agents may notify one another that something changed, but every fact that can affect work must first be written to canonical state.

```mermaid
flowchart TD
    H[Human] --> L[Liaison or UI]
    L --> DB[(SQLite state and event log)]
    DB --> M[Manager reconciler]
    M --> DB
    P[Installed policy packs] --> M
    P --> DB
    DB --> Q[Ready tasks]
    Q --> W1[Worker]
    Q --> W2[Worker]
    Q --> B[Briefer]
    W1 --> DB
    W2 --> DB
    B --> DB
    DB --> V[Generated board]
    DB --> X[Audit ZIP]
```

The manager does not need to know the full task plan at the beginning. It starts with a small discovery wave, combines the evidence, creates the next justified work, and repeats. This is called progressive fan-out.

## What is included

- `swarmctl.py`: the CLI and orchestration engine.
- `bin/swarmctl`: a portable launcher.
- `SETUP_AGENT.md`: a complete harness-installation assignment and acceptance suite.
- `guidance/`: strict role contracts suitable for smaller or less reliable models.
- `docs/`: explanations, operating procedures, policy-pack authoring, and harness integration guidance.
- `examples/`: an ambiguous pipeline mission, runner configuration, and example policy packs.
- `docs/CLI_REFERENCE.md`: generated exact CLI syntax and options.
- `scripts/check_docs.py`: deterministic documentation and contract checks.
- `scripts/release_check.py`: source and extracted-package release verification.
- `tests/`: lifecycle, policy workflow, documentation, decision propagation, inbox, lease, and export tests.

## Requirements

- Python 3.9 or newer.
- An agent harness whose agents can read a prompt file and run local commands.
- A working directory shared by the manager and workers.

SQLite supports concurrent readers and short serialized writes. Swarmkit enables WAL mode and a busy timeout. For large distributed swarms across several machines, replace SQLite with a transactional service while preserving the same protocol.

## Five-minute setup

From the copied Swarmkit directory:

```bash
chmod +x bin/swarmctl
bin/swarmctl --root /work/my-run/.swarm init \
  --objective "Restore reliable delivery through the customer data pipeline" \
  --success "New records reach the destination" \
  --success "Backlog is accounted for without loss or duplication" \
  --success "The failure mode is monitored" \
  --constraint "Ask before destructive production changes" \
  --constraint "Preserve customer data"
```

This creates:

```text
/work/my-run/.swarm/
  state.sqlite3
  runner.json
  prompts/
  runs/
  views/BOARD.md
```

Edit `runner.json` so `command` invokes your harness. The command is an argument array, not a shell string:

```json
{
  "command": [
    "your-harness",
    "agent",
    "run",
    "--prompt-file",
    "{prompt_file}",
    "--model",
    "{model}"
  ],
  "working_directory": "/work/target-repository",
  "max_parallel": 3,
  "timeout_seconds": 3600,
  "models": {
    "manager": "your-stronger-planning-model",
    "worker": "your-lower-cost-model",
    "briefer": "your-lower-cost-model",
    "verifier": "your-stronger-review-model"
  }
}
```

Available placeholders are `{prompt_file}`, `{role}`, `{task_id}`, `{agent_id}`, `{root}`, `{workdir}`, and `{model}`. Do not put secrets in this array because invoked commands are preserved in the audit log; supply credentials through the harness's normal secret mechanism.

Check the installation and adapter without launching an agent:

```bash
bin/swarmctl --root /work/my-run/.swarm setup-check
```

Then inspect the expanded invocation:

```bash
bin/swarmctl --root /work/my-run/.swarm dispatch \
  --role manager --agent manager --dry-run
```

Start bounded orchestration cycles:

```bash
bin/swarmctl --root /work/my-run/.swarm run --max-cycles 20
```

The loop launches the manager, reconciles state, claims up to `max_parallel` ready tasks, launches workers concurrently, and returns to the manager. It stops when the mission is complete, it needs a human decision, there is no ready work, or the cycle limit is reached.

## Adding organization-specific workflows

Policy packs keep project or organization practices outside Swarmkit while
making their stages durable and enforceable. A pack contributes declarative
tasks, dependencies, fresh-agent constraints, and additional task guidance. It
does not add provider credentials or executable code to the core.

Validate and install the bundled PR-review example:

```bash
bin/swarmctl policy validate examples/policy-packs/pr-adversarial-review

bin/swarmctl --root /work/my-run/.swarm policy install \
  examples/policy-packs/pr-adversarial-review \
  --actor human
```

Apply it when a workstream will produce a pull request:

```bash
bin/swarmctl --root /work/my-run/.swarm policy apply \
  pr-adversarial-review \
  --workstream WS-ID \
  --var 'goal=prevent duplicate replay records' \
  --var 'test_command=python3 -m unittest' \
  --ready
```

This creates five ordered tasks: implement and open the PR, run the harness's
`adversarial-review` skill, remediate and restore green checks, run the skill
again from a fresh agent identity, and resolve any final findings. See
[Policy packs](docs/POLICY_PACKS.md) for the contract and authoring guide.

## Answering a blocked question

List canonical decisions:

```bash
bin/swarmctl --root /work/my-run/.swarm decision list
```

Record the answer:

```bash
bin/swarmctl --root /work/my-run/.swarm decision resolve D-EXAMPLE \
  --answer "Pause ingestion for the controlled repair window" \
  --actor human
```

Do not send the answer directly to the worker. Resolution emits an event and makes affected work eligible to resume. The next owner must acknowledge the decision version before checkpointing or completing the task. Restart `run` after answering if the prior invocation stopped in `WAITING_FOR_DECISION`.

If the answer later changes, use `decision revise`; the new version invalidates old acknowledgments and fences active owners. Use `decision link` when the same answer affects additional tasks.

## Getting status

`views/BOARD.md` is generated from SQLite and must not be edited manually:

```bash
bin/swarmctl --root /work/my-run/.swarm board
bin/swarmctl --root /work/my-run/.swarm report
bin/swarmctl --root /work/my-run/.swarm doctor
bin/swarmctl --root /work/my-run/.swarm status
```

Your existing UI or cron job can invoke these commands. `report` writes `views/STATUS.md` with the mission, major workstreams, expected timing, human needs, invariant failures, failed runs, and active work. A status agent is optional; most status reporting should be deterministic formatting of the canonical state.

Record a mutable operational fact with a source and expiry:

```bash
bin/swarmctl --root /work/my-run/.swarm fact record \
  --subject "destination-api-health" \
  --value "healthy; controlled write succeeded" \
  --source "health check and request ID req-123" \
  --actor worker-2 \
  --task T-EXAMPLE \
  --ttl-seconds 300
```

A new current fact with the same subject supersedes the previous one. The reconciler expires facts after their deadline, preventing an old observation from remaining current indefinitely.

## Exporting a completed run for review

```bash
bin/swarmctl --root /work/my-run/.swarm export \
  --output /work/exports/pipeline-run.zip \
  --include-artifacts
```

The archive contains:

- the SQLite database;
- a complete chronological `events.jsonl`;
- mission, task, decision, acknowledgment, and artifact records;
- all generated agent prompts;
- captured harness stdout and stderr;
- the final board and invariant report;
- registered artifacts up to the configured per-file size limit;
- `REVIEW_ME.md`, which tells a future reviewer how to audit the run.

Prompts and captured output can contain confidential information. Inspect the archive before moving it outside the trusted environment.

## Why this works with less capable models

Smaller models need less implicit judgment and more executable structure. Swarmkit places the important behavior in mechanisms they cannot accidentally omit:

- SQLite enforces durable records and relationships.
- The CLI enforces leases, ownership, task transitions, decision acknowledgment, and completion evidence.
- Generated prompts include the exact mission, task, decisions, unseen events, agent identity, and command prefix.
- Role guides provide one short algorithm per invocation.
- The reconciler computes readiness rather than asking a model to remember dependencies.
- Audit exports make repeated failures measurable instead of anecdotal.

Do not compensate for a weaker model with one enormous prompt. Give it a narrow role, current state, exact commands, bounded choices, and observable completion criteria. See [Designing for smaller models](docs/MODEL_GUIDANCE.md) for the detailed guidance.

## Operating principle

The system should spend parallelism on gathering independent evidence. It should converge before tightly coupled changes. One worker owns a coherent implementation; short-lived agents can investigate, brief, and verify around it.

Start with the [User manual](docs/USER_MANUAL.md) for common journeys. See [System explainer](docs/SYSTEM_EXPLAINER.md) for the architecture, [Harness integration](docs/HARNESS_INTEGRATION.md) for the adapter contract, [Policy packs](docs/POLICY_PACKS.md) for workflow extensions, [CLI reference](docs/CLI_REFERENCE.md) for exact syntax, [Documentation policy](docs/DOCUMENTATION_POLICY.md) for change requirements, and [setup-agent playbook](SETUP_AGENT.md) when moving the package to a new harness machine.

To exercise the state machine without an AI harness, run the synthetic demonstration against a new directory:

```bash
python3 examples/demo_lifecycle.py \
  --root /tmp/swarmkit-demo/.swarm \
  --output /tmp/swarmkit-demo-audit.zip
```
