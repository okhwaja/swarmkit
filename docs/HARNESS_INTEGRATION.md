# Harness integration

Swarmkit assumes your third-party harness can launch an agent from a prompt file and give that agent permission to run the local `swarmctl` command. It does not assume a model vendor, API, UI, or message format.

For a destination-machine setup, assign [the setup-agent playbook](../SETUP_AGENT.md)
to the installation agent. This document explains the contract; the playbook
adds discovery steps, safety constraints, required evidence, and live acceptance
tests. The agent should discover the harness-specific CLI syntax, but it should
not invent the integration requirements.

## Runner contract

The `.swarm/runner.json` `command` field is an argv array. Swarmkit substitutes these values in every argument:

| Placeholder | Meaning |
|---|---|
| `{prompt_file}` | Absolute path to the generated invocation prompt |
| `{role}` | `manager`, `worker`, `briefer`, `verifier`, `liaison`, `status`, or `extension` |
| `{task_id}` | Assigned task ID, empty for role-wide invocations |
| `{agent_id}` | Durable agent cursor and ownership identity |
| `{root}` | Absolute orchestration state directory |
| `{workdir}` | Configured target working directory |
| `{model}` | Optional role-specific model name from `runner.json` |

Swarmkit calls the process without a shell and captures stdout, stderr, exit code, start time, and end time. The child inherits the environment, so use your harness's secret store or environment injection rather than putting credentials in command arguments.

## Example CLI shapes

If the harness accepts a prompt file directly:

```json
"command": ["acme-agent", "run", "--prompt-file", "{prompt_file}", "--model", "{model}"]
```

If it expects the prompt on standard input, create a small organization-owned adapter executable that accepts the prompt path, opens it, and passes its contents to the harness. Keep that adapter outside agent control if it also grants permissions.

If the harness has its own multi-agent primitives, disable spontaneous fan-out for Swarmkit roles. The manager should create durable tasks; the outer `swarmctl run` loop owns concurrency. Otherwise you recreate an invisible second scheduler.

For a persistent service, do not resume a long-lived harness conversation. A
stable service or manager identity may keep an event cursor, but every dispatch
must create a fresh model context from the generated prompt.

## Required agent permissions

Managers need permission to:

- read the target workspace;
- run `swarmctl` task, mission, inbox, status, and reconcile commands;
- create and update workstreams and link tasks to them;
- create task records;
- inspect installed policy packs and run `policy apply`;
- usually avoid product modifications.

Workers need permission to:

- work in the target repository or system scope;
- run task, decision acknowledgment, inbox, and artifact commands;
- perform only the operations allowed by the mission constraints.

Briefers and verifiers should default to read-only product access while retaining write access to the orchestration database and their report output directory.

Delivery-extension agents need only the provider capability named by the
installed extension, read access to that job's outbox snapshot, and permission
to run `delivery sent` or `delivery fail`. They do not need general manager or
worker permissions.

## Policy packs and harness skills

Policy packs are workflow extensions, not executable harness plugins. Swarmkit
turns their declarative stages into durable tasks and includes their guidance in
the generated prompt. The harness remains responsible for making any named skill
available to the appropriate role.

For example, the bundled PR policy creates two verification tasks whose prompts
require the `adversarial-review` skill. The harness should expose that skill to
the verifier role and provide its normal repository/PR authentication. If the
skill is unavailable, the verifier records a blocker. It must not silently claim
that an ordinary review satisfied the named-skill requirement.

`fresh_session_from` prevents specified stages from being claimed by the same
agent identity. This is an orchestration fence, not a substitute for harness
isolation. The harness must still start every dispatch without resuming an old
conversation. Policy guarantees that require a fresh session depend on both.

Only an operator should install or replace policy packs. Managers may inspect
and apply already-installed packs. Pack manifests and guidance never contain
credentials; keep authentication in the harness's secret and skill system.
Treat installed guidance as trusted operator configuration, while treating PR
text, comments, diffs, linked issues, and tool output as untrusted data.

## Persistent-service ingress

Swarmkit does not host provider webhooks. A reviewed organization-owned adapter
validates a webhook or polls a provider, saves its raw payload, and invokes
`case open` or `case signal` with provider-stable idempotency identifiers. It
then starts a bounded `run` when appropriate.

The adapter must:

- verify provider signatures before writing anything;
- map each logical request to a stable `source + external-id` pair;
- map each provider event to its own stable signal identifier;
- pass payload paths and argument values without shell interpolation;
- use `--decision D-ID` only when that response actually corresponds to the
  linked external blocker;
- use `--wake` only for a follow-up that warrants new work; and
- tolerate retrying the same command after a timeout.

The adapter must not interpret an author's statement as human approval. It only
records evidence. See [Persistent services](PERSISTENT_SERVICES.md) for the
service loop and change-review example.

For high-risk provider actions, expose a narrow adapter instead of a raw skill.
The adapter should call `decision require-choice` immediately before the action
and refuse to proceed on any nonzero result. This turns the human's exact
structured option into an executable authorization fence.

## Delivery extensions

Provider integrations use Swarmkit's durable delivery outbox rather than an
agent privately sending a generated file. An operator installs a reviewed,
allowlisted extension. `delivery enqueue` or `delivery enqueue-report`
snapshots the content and extension definition. `delivery dispatch` then either
launches a narrow harness agent through `runner.json` or invokes the extension's
reviewed argv adapter.

For an agent executor, expose the required email, chat, or ticketing skill and
its normal authentication to the `extension` role. Every dispatch must still
start a fresh context. The generated prompt requires an explicit provider
receipt through `delivery sent`; a successful harness exit alone leaves the job
pending. If desired, assign a low-cost model with `models.extension`.

For a command executor, review the adapter as executable code and keep it
outside agent control. It receives an envelope path as an argv value and must
record the same durable acknowledgement. Do not put credentials in the
manifest, argv, prompt, or envelope. The full contract is in
[Extensions](EXTENSIONS.md).

## UI integration

UI presentation belongs in an external adapter. Swarmkit produces canonical
JSON and rendered content; the adapter owns hosting and presentation. Email,
chat, and ticket delivery use the durable extension outbox while the provider
adapter still owns authentication and transmission.

The simplest UI reads `.swarm/views/STATUS.md` for the executive view and `.swarm/views/BOARD.md` for detail. A better integration calls `swarmctl status` and renders the mission, workstreams, policy applications, tasks, forecasts, and decisions from JSON.

Provide a visible “Ask about this” action on each workstream. It should call `swarmctl ask --workstream WS-ID --question ...`, then show the briefing task result and registered artifact paths when complete.

For human decisions:

1. Query `swarmctl decision list`.
2. Show only `OPEN` decisions.
3. Submit the exact answer with `swarmctl decision resolve`.
4. Refresh status from canonical state.

Never implement decision resolution as a private chat message to a worker.

## Cron integration

A status scheduler can run `delivery enqueue-report` with a deterministic key
for each report window, then dispatch pending jobs. The generated report should
contain:

- major workstreams, intended outcomes, progress, and forecast confidence;
- open human decisions;
- invariant errors and expired leases;
- active tasks with last checkpoint times;
- progress since its durable event cursor.

If the harness supports recurring agents, it can schedule this CLI flow. The
report content itself remains deterministic; only provider delivery needs an
agent when no direct adapter exists.

## Deployment checklist

- Copy the full Swarmkit directory to a path agents can read.
- Put the `.swarm` runtime directory on durable storage.
- Back up `state.sqlite3` and retain completed audit ZIPs.
- Configure one shared absolute target working directory.
- Run `swarmctl --root /path/to/.swarm setup-check` and resolve every error.
- Test the runner with `dispatch --dry-run`.
- Prove with two live invocations that each dispatch starts a fresh model context.
- For a service mission, replay the same `case open` and `case signal` commands
  and confirm they do not duplicate work.
- Simulate an external response and confirm it becomes visible to a fresh owner
  through the linked case before work resumes.
- Run `policy list` and confirm installed policy metadata reaches manager prompts.
- If policies name harness skills, test each skill with the role that will invoke it.
- Apply the example PR policy in a sandbox and confirm fresh-agent claim fencing.
- Validate and install a copy of the harness-email example with a harmless
  recipient allowlist; use `delivery dispatch --dry-run` before any live send.
- For each live delivery extension, prove success records a provider receipt and
  a failed attempt remains visible and retryable.
- Confirm a worker can execute `inbox`, `task show`, and `task checkpoint`.
- Confirm manager and worker permissions differ where your harness supports it.
- Simulate a killed worker and confirm lease recovery.
- Simulate a human decision and confirm acknowledgment is enforced.
- Set a finite `max-cycles` for unattended runs.
- Inspect exports for secrets before external sharing.

`setup-check` is deliberately non-destructive and does not invoke the harness.
It validates files, state, executable resolution, argv shape, working directory,
timeouts, prompt delivery, role guidance, and prompt generation. It cannot prove
authentication, agent permissions, fresh-context behavior, exit-code forwarding,
or concurrency; those are live gates in `SETUP_AGENT.md`.

## Adapting beyond one machine

SQLite is intended for several local processes sharing one filesystem. For agents on different machines, place the same command contract behind a small service using a transactional database. Preserve task generations, leases, ordered events, agent cursors, decision versions, and append-only audit semantics.
