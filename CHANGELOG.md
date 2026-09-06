# Changelog

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
