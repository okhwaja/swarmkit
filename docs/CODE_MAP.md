# Find your way around the code

Swarmkit is a command-line program backed by SQLite. The runtime has no third-party
Python dependencies. Start with the module that owns the behavior you want to change.

| Area | Files | Responsibility |
|---|---|---|
| Entry points | `swarmctl.py`, `bin/swarmctl`, `swarmkit/__main__.py` | Launch the same CLI. The root Python file retains imports for older adapters. |
| Command interface | `swarmkit/cli.py`, `swarmkit/cli_help.py` | Parse commands, expose offline guides and workflow help, and route to domain functions. |
| CLI installation | `swarmkit/installation.py` | Publish a user-local launcher without replacing existing commands or editing shell profiles. |
| Persistence | `swarmkit/schema.py`, `swarmkit/storage.py`, `swarmkit/core.py` | Schema history, connections, state guards, transactions, IDs, and time. |
| Work | `swarmkit/tasks.py`, `swarmkit/policies.py` | Missions, workstreams, task attempts, planning limits, and reusable workflows. |
| Coordination | `swarmkit/coordination.py`, `swarmkit/decisions.py`, `swarmkit/cases.py` | Reconciliation, manager reviews, findings, external waits, decisions, service intake, and briefing inquiries. |
| Demonstration | `swarmkit/demo.py`, `examples/demo_lifecycle.py` | A synthetic end-to-end recovery without a harness. |
| Execution | `swarmkit/runtime.py`, `swarmkit/config.py`, `swarmkit/setup.py` | Runner configuration, setup checks, subprocess ownership, recovery, and scheduling. |
| Workspaces | `swarmkit/workspaces.py` | Manual, configured-command, and explicitly selected Git checkout providers; durable creation receipts and recovery. |
| Verification and actions | `swarmkit/evidence.py`, `swarmkit/effects.py`, `swarmkit/delivery.py`, `swarmkit/grants.py` | Evidence contracts, external-action receipts, resource leases, and delivery adapters. |
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

For repeatable long-history measurements, see [performance](PERFORMANCE.md) and
`scripts/benchmark_context.py`. Avoid wall-clock assertions in unit tests; assert
bounded reads and behavior, then use measurements to assess practical overhead.

The checked-in `pyproject.toml` also configures optional Black and Ruff checks:

```sh
python3 -m black --check swarmctl.py swarmkit scripts tests examples/demo_lifecycle.py
ruff check swarmctl.py swarmkit scripts tests examples/demo_lifecycle.py
```

These are development tools, not runtime dependencies. The compatibility entry
point intentionally re-exports imports; Ruff's unused-import exemption is scoped
to that file. Domain modules use ordinary explicit imports without that exemption.

Multi-query projections use `consistent_read` / `read_snapshot` from `core.py`.
They establish a stable read view and release only transactions they opened.
Keep reconciliation outside a standalone read scope: it changes canonical state
and belongs in a write transaction. Row projection helpers used after an external
lookup rely on their caller to scope the row lookup and linked reads together.

Health checks deliberately tolerate malformed values: report the affected entity
and continue checking other records. Keep ordinary domain commands strict. Health
projections batch related counts and avoid loading task result bodies; use
`scripts/benchmark_service.py` when changing those queries.

`attention.py` owns the shared decision-attention projection and scoped transitions.
`notifications.py` validates versioned event routes and advances durable cursors
with outbox enqueue. `grants.py` owns exact-scope authority, named check records,
and explicit waivers. These modules use ordinary functions and the same transaction
helpers; they do not introduce another persistence or command-execution framework.
Plan staging belongs to task creation/authorization and manager review completion.
