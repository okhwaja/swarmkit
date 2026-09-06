# Swarmkit Harness Setup Agent Playbook

Give this file to the agent responsible for installing Swarmkit on the target
machine and connecting it to the machine's third-party agent harness. Do not
ask the agent to infer the integration contract from the source code alone.

## Assignment

Install this Swarmkit package beside the target repository, connect the local
agent harness through `.swarm/runner.json`, and prove with a disposable mission
that the harness can execute Swarmkit roles and persist its results in
Swarmkit's canonical state.

You are done only when every acceptance test below passes and you have written
`SETUP_REPORT.md` in the Swarmkit directory.

## Read first

Read these files before changing configuration:

1. `README.md`
2. `docs/HARNESS_INTEGRATION.md`
3. `guidance/HARNESS_SYSTEM_PROMPT.md`
4. `docs/MODEL_GUIDANCE.md`

Treat the SQLite database and append-only event log as canonical. Markdown
status files are generated views, not an agent-to-agent message bus.

## Safety and architecture constraints

- Perform initial live tests in a disposable checkout or harmless sandbox
  directory, never against production.
- Never put secrets, tokens, passwords, or copied environment values in
  `runner.json`, generated prompts, logs, or `SETUP_REPORT.md`.
- Use an argv array. Do not construct a shell command from task text.
- Each dispatch must start a fresh model context. Do not use a harness option
  that resumes an old chat or session. Continuity comes from Swarmkit state.
- Swarmkit is the only scheduler. Disable autonomous harness fanout, delegation,
  or background workers for these invocations unless they are fully subordinate
  to the dispatched role and cannot compete for Swarmkit leases.
- The invoked agent must be able to read the generated prompt file and run the
  local `swarmctl.py` CLI in the mission root.
- Do not edit `swarmctl.py` merely to match a harness's command syntax. Prefer a
  small adapter executable. If the contract cannot be implemented without a
  Swarmkit change, stop and document the exact incompatibility.

## Discover the harness contract

Use the installed harness's local help and documentation to establish and
record:

- executable path and version;
- non-interactive invocation command;
- how it accepts a prompt file, or whether an adapter must send the file on
  stdin;
- how its working directory is selected;
- how to force a new session/context on every invocation;
- model selection syntax, if applicable;
- exit-code behavior, timeout behavior, and where stderr is written;
- required authentication and permissions, described without exposing values;
- whether two independent non-interactive invocations can run concurrently;
- whether it autonomously creates subagents and how that behavior is disabled.

Do not guess at any of these. If the harness cannot expose fresh-session
semantics or reliable exit status, record that as a blocker.

## Configure the runner

Initialize a mission root if needed:

```bash
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  init \
  --objective "Prove the local harness can execute Swarmkit roles" \
  --success "A manager persists a workstream and task" \
  --success "A worker persists a verified result and artifact" \
  --constraint "Use only disposable local files"
```

Edit `/absolute/path/to/sandbox-mission/.swarm/runner.json`. The `command`
field is an argv array. Swarmkit replaces these placeholders inside individual
arguments:

- `{prompt_file}` — absolute path to the generated role prompt; required
- `{role}` — manager, worker, verifier, briefer, liaison, or status
- `{task_id}` — the assigned task or dispatch identifier
- `{agent_id}` — unique identity for this invocation
- `{root}` — absolute mission root
- `{workdir}` — configured runner working directory
- `{model}` — configured model string

Example shape only—replace it with the target harness's real syntax:

```json
{
  "command": [
    "/absolute/path/to/harness",
    "run",
    "--new-session",
    "--workspace",
    "{root}",
    "--prompt-file",
    "{prompt_file}"
  ],
  "working_directory": "/absolute/path/to/sandbox-mission",
  "timeout_seconds": 3600,
  "model": ""
}
```

If the harness only accepts stdin, create a small executable adapter that:

1. accepts the generated prompt path as one argv value;
2. reads that file literally;
3. starts a fresh non-interactive harness invocation;
4. forwards stdout, stderr, signals, and the exact exit code;
5. performs no shell interpolation of prompt or task content.

Point `command` at that adapter and include `{prompt_file}` as an argument.

## Acceptance tests

Run these in order. Preserve command output in `SETUP_REPORT.md`, redacting only
secret values—not errors or evidence.

### 1. Static and dry-run validation

```bash
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  setup-check
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  dispatch --role manager --agent setup-manager --dry-run
```

The setup check must return `"ok": true`. Inspect the dry-run JSON and generated
prompt. Confirm the executable, working directory, and prompt path are correct.
Warnings about properties that require a live test are expected.

### 2. Manager round trip

Create a harmless objective asking the manager to create one workstream and one
small task, then run a real manager dispatch. Verify from Swarmkit—not just the
harness transcript—that the workstream and task exist:

```bash
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  dispatch --role manager --agent setup-manager
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  workstream list
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  task list
```

### 3. Worker round trip

Assign a harmless task that creates a small text artifact in the sandbox. Run a
worker dispatch. Confirm the worker checkpoints or completes the task through
the CLI, and confirm the artifact exists. A persuasive final answer in the
harness UI does not count as persistence.

Use `task list` to obtain the ready task ID, then replace `T-ID` below:

```bash
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  task claim T-ID --agent setup-worker
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  dispatch --role worker --agent setup-worker --task T-ID
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  task show T-ID
```

The final task state must have been written by the invoked worker. If the worker
exits without a durable terminal/checkpoint update, treat the integration as
failed even when its process exit code is zero.

### 4. Fresh-context test

Run two separate dispatches with distinct task and agent identifiers. Use the
harness's session metadata or logs to prove that the second invocation did not
resume the first model context. If this cannot be proved, the setup is not
complete.

### 5. Human-decision propagation test

Create a synthetic blocking decision, answer it through the liaison workflow,
and verify that a later worker invocation reads the current decision version
from Swarmkit and acknowledges that version. Do not directly message the old
worker session.

### 6. Final health and evidence

```bash
python3 /absolute/path/to/swarmctl.py --root /absolute/path/to/sandbox-mission/.swarm report
python3 /absolute/path/to/swarmctl.py --root /absolute/path/to/sandbox-mission/.swarm doctor
python3 /absolute/path/to/swarmctl.py \
  --root /absolute/path/to/sandbox-mission/.swarm \
  export --output /absolute/path/to/sandbox-mission/setup-audit.zip
```

Resolve errors. Explain any remaining warnings.

## Required setup report

Write `SETUP_REPORT.md` with:

- machine/OS, harness name, executable path, and version;
- the redacted runner configuration and any adapter path;
- authentication and permission prerequisites, without secret values;
- evidence that invocations are non-interactive and start fresh contexts;
- results for all six acceptance-test groups;
- concurrency, timeout, and retry limitations;
- exact commands an operator should use to initialize and start a real mission;
- unresolved blockers and recommended next action.

Also attach the sandbox mission's exported audit bundle. That bundle is the
artifact used later to diagnose orchestration behavior and improve Swarmkit.

## Stop and escalate when

Stop rather than improvising if the harness cannot run non-interactively, cannot
start a fresh context, cannot provide a trustworthy exit code, cannot access the
mission root, or would require embedding secrets in command arguments. Report
the observed behavior, the command used with secrets redacted, and the smallest
decision or machine change needed from a human.
