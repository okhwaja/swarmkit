# Swarmkit contributor contract

Swarmkit is a Python 3.9+ standard-library CLI for one user on one POSIX host.
Do not assume the target project uses Git: revisions and checkout references are
opaque, and workspace tools may be supplied by a harness or internal CLI.
Read `docs/DOCUMENTATION_POLICY.md` and `docs/SYSTEM_EXPLAINER.md` before changing
behavior. `docs/PRODUCT_ROADMAP.md` is direction, not a statement of shipped behavior.

## State and execution invariants

- SQLite is canonical; Markdown boards, reports, prompts, and exports are views.
- Acquire a write transaction before reading state used to authorize a mutation.
  Keep state changes and their audit event in the same transaction. Watch for
  helpers that commit: they cannot be used inside a larger atomic plan casually.
- Assemble multi-query operator views in one read snapshot. Preserve a caller's
  existing transaction; reconcile canonical state before opening a standalone
  read scope. Entity retrieval should not regenerate unrelated reports.
- A task attempt has a unique generation and fresh agent identity. Stale owners
  may not checkpoint, publish evidence, start effects, or complete work.
- Never infer an external action failed because a harness stopped. An uncertain
  effect needs provider reconciliation; its idempotency key cannot be blindly retried.
- OS process locks are live ownership signals. SQLite leases alone do not prove
  a process stopped. Do not remove lock files to recover a run.
- Decisions and external waits release workers and survive restart. The harness
  and tools own permission and credential enforcement; Swarmkit coordinates state.
- Evidence must match the contracted revision, environment, criterion, attempt,
  and mission revision. Free-text verification is legacy compatibility, not proof.
- Use sequential transactional migrations. Reject unknown and newer versions;
  never relabel an unsupported database or use `executescript` inside a migration.
- Keep independent changes in isolated workspaces. Do not modify a user's working
  tree or clean up checkouts automatically when they may contain useful changes.

## Change and release checklist

1. Classify documentation impact using `docs/DOCUMENTATION_POLICY.md`.
2. Add meaningful failure/concurrency tests for lifecycle invariants. Prefer
   temporary directories and real subprocess fault injection over sleeps alone.
3. Update the normative operational, harness, architecture, or role documentation
   alongside code. Regenerate `docs/CLI_REFERENCE.md`; never hand-edit it.
4. Update version and changelog for a release, then run:
   `python3 -B scripts/generate_cli_docs.py`, `python3 -B scripts/check_docs.py`,
   and `python3 -B scripts/release_check.py`.
5. Review the complete code/documentation diff for semantic gaps before merging.
   The release check exercises both source and extracted distribution packages.

Do not commit local mission databases, run logs, credentials, Python caches, or
unrelated user files. Add unresolved product decisions to `docs/ROADMAP_BACKLOG.md`.
