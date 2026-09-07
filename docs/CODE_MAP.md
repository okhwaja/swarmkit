# Find your way around the code

Swarmkit is a command-line program backed by SQLite. The runtime has no third-party
Python dependencies. Start with the module that owns the behavior you want to change.

| Area | Files | Responsibility |
|---|---|---|
| Entry points | `swarmctl.py`, `bin/swarmctl`, `swarmkit/__main__.py` | Launch the same CLI. The root Python file retains imports for older adapters. |
| Command interface | `swarmkit/cli.py` | Parse arguments and route them to domain functions. |
| Persistence | `swarmkit/schema.py`, `swarmkit/storage.py`, `swarmkit/core.py` | Schema history, connections, state guards, transactions, IDs, and time. |
| Work | `swarmkit/tasks.py`, `swarmkit/policies.py` | Missions, workstreams, task attempts, planning limits, and reusable workflows. |
| Coordination | `swarmkit/coordination.py`, `swarmkit/decisions.py`, `swarmkit/cases.py` | Reconciliation, manager reviews, findings, external waits, decisions, and service intake. |
| Demonstration | `swarmkit/demo.py`, `examples/demo_lifecycle.py` | A synthetic end-to-end recovery without a harness. |
| Execution | `swarmkit/runtime.py`, `swarmkit/config.py`, `swarmkit/setup.py` | Runner configuration, setup checks, subprocess ownership, recovery, and scheduling. |
| Workspaces | `swarmkit/workspaces.py` | Manual, configured-command, and explicitly selected Git checkout providers. |
| Verification and actions | `swarmkit/evidence.py`, `swarmkit/effects.py`, `swarmkit/delivery.py` | Evidence contracts, external-action receipts, resource leases, and delivery adapters. |
| Agent context | `swarmkit/prompts.py`, `swarmkit/inbox.py` | Fresh role prompts and durable event delivery. |
| Read models | `swarmkit/queries.py`, `swarmkit/views.py` | JSON projections, boards, and operator reports. |
| Integrity and export | `swarmkit/diagnostics.py`, `swarmkit/audit.py` | Consistency checks and portable audit bundles. |

The modules contain ordinary functions and explicit imports. There is no plugin
loader, dependency-injection container, or entity repository layer between a domain
operation and its SQL. The command line is the stable integration interface. Python
adapters can import the owning module; tests patch dependencies where they are used.

## Changing durable state

A connection-first command uses `@atomic_write`. A command that also takes a root
path uses `with transaction(conn)`. Both acquire a write transaction before reading
state that authorizes a mutation. Related changes and audit events commit together.

A helper called inside an existing transaction uses a savepoint. It never commits
its caller's work. If a helper fails and the caller catches the exception, only that
helper's work rolls back. If the exception propagates, the complete outer operation
rolls back. Low-level row and event helpers intentionally do not commit.

Read-only projections do not change state. SQLite is authoritative; regenerated
Markdown, prompts, and exports must not become alternate state stores.

## Checks

```sh
python3 -B -m unittest discover -s tests
python3 -B scripts/generate_cli_docs.py
python3 -B scripts/check_docs.py
python3 -B scripts/release_check.py
```

The last command also builds a distribution, extracts it, and repeats the checks.
Use temporary mission directories in tests. Do not put live databases, run logs,
provider credentials, or generated checkouts in the package.
