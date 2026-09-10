# Changelog

## 0.14.0

- U11 adds structured, immutable decision briefs: background, human authority
  reason, option consequences/risks, recommendation, blocked outcome, and
  separately rendered evidence. Exact choice values stay compatible. New
  integrations can require briefs with `decision-contract --mode required`.
- U12 adds durable delivery commitments independent of task attempts, required
  producer handoffs, staged publication, exact-scope provider observations,
  versioned waits, idempotent signals, explicit adoption, and audited cancellation.
  Open obligations remain visible and prevent task-derived success from hiding
  unlanded changes.
- Added the author-to-merge policy and a bounded reference provider-observation
  checker. Harnesses supply real provider access, permissions, scoped grant
  issuance, babysitting skills, and reliable wakeups. The integration tests exercise
  human release through repairs and merge, including a lost provider response.
- Schema 14 upgrades preserve legacy decisions and tasks. No delivery obligation
  or human authority is inferred from historical prose. Back up state before
  upgrade; older releases cannot read schema 14.
- Proposed-task external-condition gates remain deferred; existing task waits
  support review/repair/merge continuation.

## 0.13.0

- Decision revisions preserve the existing structured choice unless explicitly
  replaced or cleared. Informational decision references no longer need to act
  as authorization gates.
- Manager reviews have fresh attempt identities, durable capped backoff, an
  explicit retry limit/reset, and restart-safe escalation. New plan authorizations
  publish together after a successful review while committed work keeps running.
  Normal review cooldown is configurable and does not delay urgent reviews.
- Open decisions appear in the shared attention view with ages and affected work.
  Human-block and aging transitions can feed opt-in, versioned notification routes
  through the existing immutable outbox, with durable cursors and replay protection.
- Quiescent task acceptance can be amended without replacing task IDs or deleting
  evidence. Amendments require reapproval and fresh attempt-bound verification.
- Added exact-scope conditional grants, trusted check records, explicit waivers,
  revocation, and grant-bound effect-start checks. Harnesses retain permission
  enforcement and provider execution.
- Service output explicitly identifies exhausted polling budgets. Agent and
  delivery dispatch share the configured live-process capacity.
- Sequential schema 13 migration retains historical decisions, task attempts,
  evidence, and manager review leases. Back up state before upgrade; older binaries
  cannot read the upgraded database.

## 0.12.0

- Install the bundled `swarmctl` command with `./bin/swarmctl install`. The launcher
  works outside the package directory, pins its package and Python interpreter,
  and preserves existing different commands. No downloads or shell-profile edits.
- Added offline `swarmctl guide [topic]` for agents and humans, plus
  `swarmctl help [command ...]`. Bare invocation shows help without mission access.
- Command help now describes common workflows, side effects, and next actions.
  Product documentation uses the installed CLI and explains PATH setup for agents.
- Python entry points and pinned role invocations remain compatible. No schema
  change from 12.

## 0.11.2

- Private audits omit runtime symlinks and special files rather than following
  them into unrelated content. `runtime-export.json` explains omissions.
- Handle logs, intake payloads, and registered artifacts that disappear or become
  unreadable during copying; retain the canonical snapshot and report missing
  evidence. Failed archive publication still preserves the previous output.
- No schema change from 12.

## 0.11.1

- Preserve unfinished harness/sender runs when process supervision raises before
  proving the child stopped. Inherited locks remain authoritative for recovery;
  the scheduler stops allocating more work and reports `RECOVERY_WAIT`.
- Journal stdout/stderr paths before launch so interrupted-run logs are discoverable.
- Keep health checks useful on malformed timestamps, JSON, missing sender leases,
  and files that disappear during hashing; report all observed problems.
- Batch health projections for tasks/workstreams/cases and avoid reading result
  bodies unnecessarily. Scope duplicate-title warnings to one workstream.
- Updated generic workflow packs to 1.1.0: local review artifacts, VCS-neutral
  handoffs, independent verifiers, evidence-based no-change performance outcomes,
  explicit port compatibility scope, and reuse of already-recorded authority.
- No schema change from 12.

## 0.11.0

- Added `evidence show --task` with specific missing, stale, failed, unavailable,
  changed-file, and passing statuses. It uses the same current result as completion.
- Added bounded `evidence list --task --limit --before` history with a stable cursor.
- Added optional `evidence record --idempotency-key`. Exact retries return the
  original record without new evidence, artifacts, or events; retrying an old pass
  cannot overtake a later failed rerun. Changed targets or result contents fail.
- Schema 12 adds task-scoped evidence keys and indexes for current-result and
  history lookups. Existing evidence records remain unchanged.

## 0.10.1

- Validate runner and adapter argv templates before allocating work; reject
  unknown or malformed placeholders, NUL arguments, non-string model values,
  and non-finite scheduling intervals. Setup checks use the runtime validator.
- Render `{workdir}` from the final checkout lookup used as the process directory.
- Allow an explicit same-attempt re-prepare after provider-confirmed `NOT_APPLIED`;
  retry identical reconciliation acknowledgments without duplicate events.
- Make workstream cancellation retire unfinished tasks and dependents atomically,
  with a required summary. Case workstreams use `case cancel` to preserve lifecycle
  consistency. Completed results and uncertain external actions remain recorded.
- No schema change; schema 11 remains compatible.

## 0.10.0

- Bound newly coalesced manager reviews to 50 triggers each. A burst creates
  serialized batches instead of repeatedly rewriting one growing JSON document.
  Indexed identity lookups deduplicate requests across all pending batches.
- Escalate an existing normal review when its trigger is repeated as urgent;
  retain its original ordered trigger rather than duplicating it.
- Added paginated `review list` summaries and complete `review show` retrieval.
  Manager prompts retain their active review ID through context overflow and
  prioritize running reviews. Replaced an invalid prompt retrieval command.
- Recheck checkout state in the run-registration transaction. Unresolved checkout
  work blocks claims without consuming attempts; the scheduler reports
  `WAITING_FOR_WORKSPACE` with a recovery next step.
- Use the newest verification record per criterion/target/attempt. A later failed
  rerun supersedes an older pass. Evidence and artifact hashes come from one file
  observation, and shared result paths are hashed once per completion check.
- Verify copied intake payloads against their recorded hashes and sizes; omit
  changed/missing payloads with explicit `intake-export.json` explanations.
- Keep status, health, explanation, and entity reads in consistent SQLite
  snapshots. Targeted list/show commands no longer regenerate whole-mission
  reports. Brief status exposes pending checkout recovery directly.
- Schema 11 adds the review-trigger identity index and review ordering index.
  Existing review payloads/order are preserved, including legacy oversized
  batches. New triggers spill into bounded batches; semantic commits still
  require one disposition per trigger.

## 0.9.0

- Journal checkout creation before invoking Git or a configured internal CLI.
  Lost receipts, timeouts, and controller loss cannot replay a potentially
  successful creation, including providers that allocate their own paths.
- Added `workspace attempts` and `workspace reconcile`, retained provider logs,
  and preserved successful receipts across pause/expired ownership. Repeat create
  attaches a known checkout without invoking the provider again.
- Blocked dispatch, resume, amendment, completion, and drain finalization where
  an unresolved creation would hide live or uncertain work. Reconciliation uses
  inherited process locks and remains available during pause/cancellation.
- Schema 10 adds the creation journal; existing workspace registrations remain.
- Added retriable `case apply-policy` and atomic `--replace` with an explicit key
  and rationale. Replacements preserve completed work and human decisions, refuse
  cross-case cancellation and unrecovered harnesses/effects, and roll back fully
  if new planning fails. Existing policy-key storage is reused without migration.

- Batch task eligibility and active-case reconciliation reads. A 1,000-case /
  5,000-task fixture reduced unchanged-pass reads from 6,009 to 9 and measured
  about 50 ms to 11 ms locally. Added an active-service benchmark and invariant
  tests for query counts, human/wait precedence, and terminal outcomes.

## 0.8.0

- Split the engine into explicit storage, domain, runtime, context, and presentation
  modules. Retained the CLI and root Python compatibility imports; added a code map
  and consistent optional development-tool configuration.
- Made domain mutations atomic and composable with savepoints. Case intake,
  signals, policy plans, and inquiries roll back together; failed intake cleans up
  its new payload files and rejects payload fingerprint/copy races.
- Bound prompt and inbox reads in SQL before JSON decoding. Added scoped indexes,
  newest-first case context, explicit retrieval pages, and a repeatable history
  benchmark. A 25,000-event fixture reduced measured Python allocation peaks from
  about 55–58 MB to about 0.2 MB for prompts and inbox leases.
- Bound decision acknowledgements to the current owner. Revised/linked decisions
  retire obsolete attempts and waits; executing actions remain uncertain.
- Added `UNKNOWN` delivery outcomes and `delivery reconcile`. Missing receipts,
  timeouts, expired claims, and controller loss no longer permit blind replay.
  Delivery logs stream to files; recovery uses inherited process locks.
- Applied pause/cancel fencing to manager reviews. Drain includes workers,
  manager reviews, delivery claims, and unclosed sender processes. Resume and
  amendments require delivery recovery/reconciliation too.
- Distinguished successful, partial, and cancelled completion. Cases/workstreams
  expose completion outcomes; mission completion defaults to `PARTIAL` when work
  was cancelled, with an explicit evidence-backed override. Cancel propagates to
  descendants and withdraws obsolete questions. Follow-ups clear stale summaries.
- Added whole-policy application retry keys and durable signal-to-task identity.
  Identical retries return existing work; changed requests under a key are rejected.
- Added an isolated harness-free `demo`, concise `status --brief`, and
  `decision show`. Rewrote first-use documentation. Initialization stages a complete
  database under a process lock and preserves existing runner configuration.
- Allowed active owners to use `workspace create --agent`. Checkout children retain
  creation locks after controller loss. Manual/internal/jj workflows remain the
  default integration path; Git remains an explicit provider.
- Allowed the current owner to bind an initially absent evidence contract to a
  newly produced revision. Pinned targets cannot change during the attempt.
  Rejected blank task goals/criteria, empty questions/answers, and malformed manifest
  input without tracebacks. Withdrawn questions cannot gate new work.
- Made audit publication atomic, streamed archive/event data, preserved the exact
  recorded database snapshot, and added a counter-only share-safe path that never
  stages private content. Manifest validation returns useful corruption errors.
- Restricted distribution contents to source/documentation roots, excluded local
  mission data and symlinks, normalized ZIP metadata, and preserved old output on
  packaging failure. Added local-runtime Git ignores.
- Schema 9 adds context/run indexes, completion outcomes, workflow retry keys, and
  signal/task links. It backfills outcome/link history and fences known ambiguous
  legacy deliveries as `UNKNOWN`. Stop old controllers before upgrade and keep a
  pre-upgrade backup; older releases cannot read schema 9.
- Expanded the suite from 71 to 167 tests, including real controller kills,
  transaction/commit failure injection, migration, privacy, idempotency, and
  VCS-neutral checkout tests. Runtime remains Python 3.9+ and standard-library only.


## 0.7.1

- Removed the implicit Git assumption from workspace creation. Default to
  harness-managed checkouts; Git worktrees are an explicit optional provider.
- Added configurable shell-free checkout commands with bounded timeouts and JSON
  receipts, plus registration of checkouts created by jj/internal harness tools.
- Treat base revisions and checkout references as provider-specific opaque values;
  dispatch uses the registered directory without requiring Git metadata.
- Added ownership/isolation checks, immutable registration, missing-checkout
  diagnostics, adapter failure handling, and provider setup validation.
- Schema 8 preserves existing Git registrations while adding provider and
  requested-base provenance. Existing workspaces still dispatch; select Git
  explicitly for future creation. Added non-Git adapter and migration tests.

## 0.7.0

- Added crash-safe attempt records, POSIX controller/process locks, recovery,
  launch-error/timeout handling, and fresh-identity stale-owner fencing.
- Added durable mission pause, drain, resume, cancel, abandon, amendments, and
  cancellation propagation to dependent tasks.
- Added an external effect ledger with idempotency keys, exact action parameters,
  provider receipts, uncertain-state reconciliation, and replay refusal.
- Added leased inbox batches and explicit acknowledgments, task worktrees,
  exclusive resource leases, criterion evidence contracts, task planning keys,
  and strict semantic manager review commits.
- Added bounded immutable prompt packets, model/attempt provenance, optional
  attempt-based model escalation, deterministic why diagnostics, persistent
  limits, bounded service polling, and explicit escalation on exhausted retries.
- Made audit views derive from one SQLite snapshot; added artifact integrity
  rejection, manifest verification, and structural-only share-safe exports.
- Added performance, pipeline repair, and system port policy templates and a
  contributor contract. Updated operating/setup/harness/role documentation.
- Schema 7 upgrades known schemas transactionally and rejects unsupported newer
  versions. Stop old controllers before upgrading. Existing free-text verification
  remains compatible; opt into strict evidence. Use fresh agent IDs on reclaim.
- Added lifecycle races, process-kill recovery, migration rollback, uncertain
  effect, evidence, inbox, workspace, and audit tests. Runtime locking requires
  Python 3.9+ on macOS/Linux. See docs/ROADMAP_BACKLOG.md for remaining scope.

## 0.6.0

- Replaced worker-wave scheduling with a bounded event-responsive loop that
  can review completed work and reuse freed capacity while unrelated tasks run.
- Added durable, coalesced, serialized manager reviews with urgent wakeups and
  audit latency metrics.
- Added evidence-backed `ROUTINE`, `MATERIAL`, and `URGENT` findings with
  required manager dispositions and links to resulting work.
- Added ownerless `WAITING_EXTERNAL` tasks, scheduled checks, idempotent
  external signals, mandatory deadlines, and fresh verification attempts.
- Added responsive state to prompts, inboxes, boards, executive reports,
  health checks, snapshots, and audit exports.
- Added automatic schema-v6 migration for existing mission roots; existing
  task, lease, dependency, decision, policy, extension, and case behavior is
  preserved.
- Added deterministic tests for every responsive-orchestration acceptance
  scenario plus CLI round trips and harness-process exit behavior.

## 0.5.0

- Added `SERVICE` missions for persistent logical agents whose model contexts
  are replaced on every invocation.
- Added idempotent cases with dedicated workstreams, immutable intake payloads,
  policy applications, derived lifecycle state, and audit coverage.
- Added idempotent case signals for author responses, new revisions, provider
  events, external-blocker resolution, and explicit follow-up wake tasks.
- Added complete case context to generated prompts and task-scoped event inboxes.
- Added the provider-neutral `human-gated-change-review` example policy.
- Added persistent-service setup, ingress, scheduling, human-gate, operations,
  and smaller-model guidance.
- Extended the documentation and extracted-package release gates for service
  mode, public case commands, and both bundled policy workflows.

## 0.4.0

- Added reviewed delivery extensions with agent and direct-command executors.
- Added a durable, hashed outbox with recipient allowlists, idempotency keys,
  leases, explicit provider acknowledgements, failures, and retries.
- Added `delivery enqueue-report` so schedulers can generate executive status
  content separately from provider transmission.
- Added extension and delivery state to boards, status reports, health checks,
  and audit exports.
- Added the harness-email example and operator, setup, integration, and
  extension-authoring documentation.
- Extended the release gate to validate delivery-extension docs, manifests,
  lifecycle tests, and extracted package behavior.

## 0.3.0

- Added declarative policy packs for organization- and project-specific agent
  workflows without hard-coding those workflows into Swarmkit.
- Added durable policy applications that expand a policy into an auditable task
  dependency graph.
- Added fresh-agent constraints between policy stages.
- Added the `pr-adversarial-review` example policy with two separate adversarial
  reviews and remediation gates.
- Added a generated CLI reference plus source and extracted-package
  documentation/release checks.

## 0.2.1

- Added the destination-machine setup-agent playbook and `setup-check` command.

## 0.2.0

- Added first-class executive workstreams, forecasts, briefings, and status
  reporting.
