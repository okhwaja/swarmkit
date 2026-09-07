# Swarmkit

Swarmkit helps agents carry work across short conversations, long waits, and
restarts. Give it an outcome; a manager agent makes a plan, workers carry out
bounded tasks, and a local database preserves the work and the decisions behind it.

Use it with an agent harness you already have. Swarmkit supplies coordination,
not an AI model, provider credentials, or permission to take external actions.
It runs on one POSIX machine with Python 3.9+ and the standard library. There is
no Python package installation or server to configure.

## Is this for me?

It is useful when work needs several investigations, fresh reviewers, human
answers, or external jobs that may take hours:

| Your goal | How Swarmkit helps |
|---|---|
| “Customers say this is slow.” | Investigate, benchmark, implement, and verify with a shared record of evidence. |
| “Restore this broken pipeline.” | Track diagnosis and repair; release workers while waiting for approval or a provider job. |
| “Keep reviewing incoming changes.” | Use a service mission with durable cases, deduplicated signals, and a reviewed workflow. |
| “Port this system and prove it still works.” | Divide the port into independent tasks, then require integration and verification. |

A single short agent session may be enough for a small edit. Swarmkit is intended
for work where durable coordination earns its extra setup. It does not run a
distributed fleet or include ready-made GitHub, email, or pipeline integrations.
Your harness or adapters provide those tools.

## Try it without an agent

From the copied or extracted project directory:

```sh
python3 swarmctl.py demo
python3 swarmctl.py --root swarm-demo/.swarm status --brief
```

The demo creates `swarm-demo/`, walks through a **synthetic** pipeline repair and
human approval, and writes a readable report plus an audit ZIP. It makes no model
or provider calls. Open `swarm-demo/.swarm/views/STATUS.md` to see the result.
The demo refuses to overwrite an existing run and ignores `SWARM_ROOT` unless
you explicitly pass `--root`.

## Start real work

**1. Describe the outcome.** Choose a state directory outside your source checkout
when convenient. It does not need to be a Git repository.

```sh
python3 swarmctl.py --root /work/pipeline/.swarm init \
  --objective "Restore reliable pipeline delivery" \
  --success "New records arrive and the backlog is accounted for" \
  --constraint "Ask before production changes"
```

**2. Connect your harness.** Edit the generated `runner.json`: set `command` to
your harness's argument array and `working_directory` to the target project.
For example, **if your harness accepts this syntax**:

```json
{
  "command": ["my-agent", "--prompt-file", "{prompt_file}"],
  "working_directory": "/work/source",
  "workspace": {"provider": "manual"},
  "max_parallel": 3
}
```

Every invocation must start a fresh agent session that reads the prompt and can
run Swarmkit commands. The harness enforces tool permissions and supplies secrets.
See the [integration contract](docs/HARNESS_INTEGRATION.md), or give an agent the
[setup assignment](SETUP_AGENT.md) to discover your machine's exact syntax and
verify the integration. `init` preserves an existing `runner.json`.

Check the configuration without launching an agent:

```sh
python3 swarmctl.py --root /work/pipeline/.swarm setup-check
```

**3. Run and follow progress.**

```sh
python3 swarmctl.py --root /work/pipeline/.swarm run --max-cycles 20
python3 swarmctl.py --root /work/pipeline/.swarm status --brief
python3 swarmctl.py --root /work/pipeline/.swarm report
```

The bounded controller stops when it completes, reaches its cycle limit, or has
no work it can currently launch. Durable state remains. Answer a pending decision
with `decision resolve`, then run again; use [the persistent controller](docs/RUNTIME_SAFETY.md)
when you want scheduled checks and signals to be handled over time. `status`
without `--brief` returns the complete JSON snapshot for tools.

## A few concepts to know

A **mission** is the overall outcome. A **task** is a bounded unit of work owned
by one fresh worker attempt. A **decision** records an answer that affected workers
must acknowledge. An **external wait** records why work is waiting and when to
check again. A **case** is one incoming request to a persistent service.

SQLite is the source of truth. Reports, prompts, and audit exports are views of
it. Completed work may have a `PARTIAL` outcome when some planned tasks were
cancelled. After an interrupted external action, an `UNKNOWN` result requires
checking the provider before another attempt.

For independent code changes, register separate checkouts created by your harness,
or configure a checkout command. Manual checkouts, `jj`, and internal monorepo
CLIs are supported without assuming Git; Git worktrees are an explicit option.
See [workspace configuration](docs/RUNTIME_SAFETY.md).

## Where to go next

- [User manual](docs/USER_MANUAL.md): operate a mission, answer questions, inspect results.
- [Policy packs](docs/POLICY_PACKS.md): reusable performance, pipeline, port, and PR workflows.
- [Persistent services](docs/PERSISTENT_SERVICES.md): cases, follow-ups, and ingress adapters.
- [Runtime safety](docs/RUNTIME_SAFETY.md): pause, recovery, evidence, effects, and workspaces.
- [CLI reference](docs/CLI_REFERENCE.md): exact syntax; every command also accepts `--help`.
- [Code map](docs/CODE_MAP.md): module ownership, transaction rules, and contributor checks.
- [Roadmap backlog](docs/ROADMAP_BACKLOG.md): remaining capabilities and integration decisions.

To create a portable release, run `python3 scripts/package.py`. It writes
`dist/swarmkit-0.11.1.zip`. Run `python3 -B scripts/release_check.py` to test both
the source tree and an extracted package. Local mission files are excluded.
