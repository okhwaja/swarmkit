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
5. `docs/POLICY_PACKS.md`
6. `docs/EXTENSIONS.md`
7. `docs/PERSISTENT_SERVICES.md`
8. `docs/RESPONSIVE_ORCHESTRATION.md`

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
  installed `swarmctl` CLI with the correct mission root.
- Do not edit `swarmctl.py` merely to match a harness's command syntax. Prefer a
  small adapter executable. If the contract cannot be implemented without a
  Swarmkit change, stop and document the exact incompatibility.

## Make the CLI available

Keep the complete package in a stable directory. From that directory, run
`./bin/swarmctl install`; use `--bin-dir` if the destination environment has a
preferred command directory. Add the printed directory to the harness's PATH as
well as your terminal's PATH. The installer does not modify shell profiles, fetch
dependencies, or replace a different existing command. Keep the package in place.

From an unrelated directory, verify `swarmctl --version`, `swarmctl guide`, and
`swarmctl help decision resolve`. If a GUI agent has a different PATH, configure
that environment explicitly or give it the installed command's absolute path.
Generated role prompts retain an absolute package command prefix so they cannot
accidentally select another installed version. Follow that prefix when dispatched.

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
- how installed harness skills are exposed to a non-interactive role invocation;
- whether required skills such as `adversarial-review` can be invoked from a
  generated task prompt.
- whether provider skills intended for delivery extensions, such as email, can
  return a durable provider receipt to a non-interactive invocation.
- for persistent services, which trusted webhook, polling, or scheduler adapter
  will invoke `case open`, `case signal`, and bounded `run` commands.
- whether the harness can sustain `max_parallel` independent processes while
  Swarmkit polls state, and whether an exited invocation releases its process
  slot promptly;
- which trusted adapters may invoke `wait signal`, how their stable source and
  external IDs are derived, and how callback authenticity is checked outside
  Swarmkit.

Do not guess at any of these. If the harness cannot expose fresh-session
semantics or reliable exit status, record that as a blocker.

## Configure the runner

Initialize a mission root if needed:

```bash
swarmctl \
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
- `{role}` — manager, worker, verifier, briefer, liaison, status, or extension
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
  "max_parallel": 3,
  "timeout_seconds": 3600,
  "scheduler_poll_seconds": 1,
  "manager_review_debounce_seconds": 1,
  "models": {
    "manager": "",
    "worker": "",
    "briefer": "",
    "extension": "",
    "verifier": ""
  }
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
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  setup-check
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  dispatch --role manager --agent setup-manager --dry-run
```

The setup check must return `"ok": true`. Inspect the dry-run JSON and generated
prompt. Confirm the executable, working directory, and prompt path are correct.
Warnings about properties that require a live test are expected.

Validate that policy-pack support survived packaging:

```bash
swarmctl policy validate \
  /absolute/path/to/swarmkit/examples/policy-packs/pr-adversarial-review
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  policy install /absolute/path/to/swarmkit/examples/policy-packs/pr-adversarial-review \
  --actor setup-agent
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  policy list
```

Confirm a generated manager prompt lists the installed policy. If this machine
will use a pack that names harness skills, run a disposable invocation of every
required skill with the intended role and record the result. A missing skill is
a setup limitation, not permission to weaken the workflow silently.

Validate that delivery-extension support survived packaging:

```bash
swarmctl extension validate \
  /absolute/path/to/swarmkit/examples/extensions/harness-email
```

If this machine will send status email, copy that example to an
organization-owned directory, replace its example recipient allowlist, review
its guidance, and install the copy. Queue a harmless test file and run
`delivery dispatch N-ID --agent setup-emailer --dry-run`. Confirm the envelope
contains only the intended subject, recipient, content path/hash, and
idempotency key. A live send requires explicit human approval and a harmless
recipient; if performed, confirm `delivery show N-ID` contains the provider
receipt. Never use a production mailing list for setup tests.

Validate persistent-service support and its example policy:

```bash
swarmctl policy validate \
  /absolute/path/to/swarmkit/examples/policy-packs/human-gated-change-review
```

If this installation will run a standing service, initialize a separate
disposable mission with `--mode SERVICE`. Submit the same harmless `case open`
command twice and confirm only one case and task graph exist. Record an
idempotent `case signal`, then prove a fresh task invocation can read it. Do not
connect a live provider webhook until signature validation, source/external-ID
mapping, and shell-free argv handling have been reviewed.

Validate responsive scheduling with a disposable mission containing one slow
task and one short task. Confirm the short task can complete, trigger a manager
review, and launch justified follow-up work before the slow harness process
exits. Raise a material finding from an active worker and confirm that a fresh,
serialized manager invocation sees and dispositions it while the worker may
continue. Routine checkpoints must not create manager reviews.

Validate external waits without using a real long delay:

1. claim a disposable task;
2. run `task wait-external` with a future check, expected signal, and deadline;
3. let the invoking process exit and confirm the task still has no owner or
   lease and remains `WAITING_EXTERNAL`;
4. call `wait signal` twice with the same source/external ID and confirm exactly
   one durable signal and one wake;
5. dispatch a fresh worker and confirm it verifies the condition rather than
   treating the signal as success; and
6. repeat with a simulated or short deadline and confirm the report demands
   attention without reporting success.

### 2. Manager round trip

Create a harmless objective asking the manager to create one workstream and one
small task, then run a real manager dispatch. Verify from Swarmkit—not just the
harness transcript—that the workstream and task exist:

```bash
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  dispatch --role manager --agent setup-manager
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  workstream list
swarmctl \
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
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  task claim T-ID --agent setup-worker
swarmctl \
  --root /absolute/path/to/sandbox-mission/.swarm \
  dispatch --role worker --agent setup-worker --task T-ID
swarmctl \
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
swarmctl --root /absolute/path/to/sandbox-mission/.swarm report
swarmctl --root /absolute/path/to/sandbox-mission/.swarm doctor
swarmctl \
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
- installed policy packs, named-skill availability, and fresh-session policy support;
- installed delivery extensions, provider-skill availability, recipient
  allowlists, and acknowledgement behavior;
- service-mode support, ingress-adapter path, idempotency behavior, and
  fresh-context evidence for standing agents;
- responsive scheduling evidence, effective parallelism and polling/debounce
  settings, finding triage behavior, external-wait signal authentication, and
  deadline behavior;
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

## Runtime acceptance (0.7.0)

Before enabling unattended work, follow [runtime setup and recovery](docs/RUNTIME_SAFETY.md).
Require Python 3.9+ on macOS/Linux. Stop old controllers before schema migration.
In a disposable mission, configure a harmless harness; claim a task with a fresh
identity, pause it, prove the old owner cannot complete it, recover, resume, and
claim from a new identity. Exercise an inbox lease/ack and an uncertain effect
without performing a real external action. Enable strict evidence and confirm a
missing or changed result file blocks completion. Verify an export with
`audit-verify`. A successful process exit alone is not a semantic manager review
commit in strict mode. Test reboot autostart separately if the owner configures it.

For workspace setup, discover the target's actual VCS and checkout tools. Do not
assume Git or install it just for Swarmkit. Prefer a one-time command adapter when
an internal checkout CLI is repeatable; otherwise have the harness create and
register a checkout. Verify an opaque base revision, distinct source/destination,
and dispatch cwd with [the adapter protocol](docs/RUNTIME_SAFETY.md#isolate-files-and-scarce-resources).
`setup-check` validates provider configuration without creating a checkout.

For unattended coordination, enable strict evidence when semantic manager commits
are required. Verify that manager identities are fresh, failed reviews stop at
the configured retry limit, and the supervisor handles scheduled retry times and
poll exhaustion. Notification routes and conditional grants are opt-in: obtain
explicit scope/recipient configuration and test their adapter using synthetic
local data before enabling provider execution. No production route or grant is
created by setup. See [conditional grants](docs/CONDITIONAL_GRANTS.md) and
[event notifications](docs/EXTENSIONS.md#event-notifications).
