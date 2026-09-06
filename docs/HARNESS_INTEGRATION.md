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
| `{role}` | `manager`, `worker`, `briefer`, `verifier`, `liaison`, or `status` |
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

## Required agent permissions

Managers need permission to:

- read the target workspace;
- run `swarmctl` task, mission, inbox, status, and reconcile commands;
- create and update workstreams and link tasks to them;
- create task records;
- usually avoid product modifications.

Workers need permission to:

- work in the target repository or system scope;
- run task, decision acknowledgment, inbox, and artifact commands;
- perform only the operations allowed by the mission constraints.

Briefers and verifiers should default to read-only product access while retaining write access to the orchestration database and their report output directory.

## UI integration

The simplest UI reads `.swarm/views/STATUS.md` for the executive view and `.swarm/views/BOARD.md` for detail. A better integration calls `swarmctl status` and renders the mission, workstreams, tasks, forecasts, and decisions from JSON.

Provide a visible “Ask about this” action on each workstream. It should call `swarmctl ask --workstream WS-ID --question ...`, then show the briefing task result and registered artifact paths when complete.

For human decisions:

1. Query `swarmctl decision list`.
2. Show only `OPEN` decisions.
3. Submit the exact answer with `swarmctl decision resolve`.
4. Refresh status from canonical state.

Never implement decision resolution as a private chat message to a worker.

## Cron integration

A status cron job can run `report`, which writes `views/STATUS.md`. It should report:

- major workstreams, intended outcomes, progress, and forecast confidence;
- open human decisions;
- invariant errors and expired leases;
- active tasks with last checkpoint times;
- progress since its durable event cursor.

If the harness supports recurring agents, generate a `status` prompt. If not, deterministic formatting is preferable and cheaper.

## Deployment checklist

- Copy the full `orchestration` directory to a path agents can read.
- Put the `.swarm` runtime directory on durable storage.
- Back up `state.sqlite3` and retain completed audit ZIPs.
- Configure one shared absolute target working directory.
- Run `swarmctl --root /path/to/.swarm setup-check` and resolve every error.
- Test the runner with `dispatch --dry-run`.
- Prove with two live invocations that each dispatch starts a fresh model context.
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
