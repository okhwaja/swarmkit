# Roadmap implementation status and backlog

Reviewed against the approved P0/P1 roadmap, with the 0.14.0 decision/delivery update
on 2026-09-10 UTC. P2 remains deferred. Releases 0.7–0.11 add tested runtime
slices across most of the active roadmap; this
is not a claim that every capability or persistent-coworker release gate is done.
The current behavior is documented in [RUNTIME_SAFETY.md](RUNTIME_SAFETY.md).

## Questions for the owner

These questions block the follow-on integrations below, not the changes shipped
through 0.13.0. No answer or permission is inferred while you are away.

| Decision | Needed before | Suggested starting point |
|---|---|---|
| Which repositories, review categories, and risk thresholds may receive automatic approval? | A production automatic PR reviewer and risk-based policy evaluator. | Explicit repository allowlist, exact head revision, green required checks, and human routing for all other cases. |
| Which pipeline/provider should be the first effect integration, and which actions support a stable idempotency key or result lookup? | An end-to-end external-action adapter with verified no-duplicate guarantees. | Start with one provider and one action whose result can be queried after a crash. |
| Should the persistent coworker start automatically on login/reboot, and on which host/OS? | Installing a launchd/systemd service and credential availability rules. | Run `serve` manually first; install user-scoped autostart after the first workflow is accepted. |
| What spend, API, and human-attention limits should apply, and which harness supplies actual usage receipts? | Monetary/token/API/attention quotas and cost-based routing. | Use the implemented run, task, failure-attempt, and deadline limits until usage receipts exist. |
| Which models and representative successful/failed runs should form the postmortem evaluation set? | Scored postmortem evaluation and model-quality promotion gates. | A small labeled set of real runs with supported-claim and causal-attribution expectations. |

## Coverage by roadmap rank

“Added” means an executable, tested slice is included; any remaining scope is
explicit. “Existing” identifies foundations present before this release.

| Rank | Capability | Current coverage and remaining work |
|---:|---|---|
| 1 | Crash-safe attempts and recovery | Added attempts, process/controller locks, startup recovery, proven launch-error/timeout closure, supervision-error preservation, and stale-owner fencing. Legacy untracked runs need an operator liveness assertion. |
| 2 | Effect ledger | Added durable intent, stable keys, receipts, unknown state, safe adoption, and replay refusal. Provider adapters and provider result verification remain. |
| 3 | Lifecycle controls | Added mission pause/drain/resume/cancel/abandon, task descendant cancellation, manager fencing, delivery-aware draining, explicit workstream cancellation, and cleanup visibility. Per-case/workstream pause and selective interruption remain. |
| 4 | Reliable inbox | Added leased batches, explicit idempotent acknowledgment, redelivery, scoped offsets, and stale-token fencing. Consumers still must deduplicate their own mutations. |
| 5 | Durable confirmations | Existing versioned decisions now close attempts as waiting; fresh attempts must acknowledge current answers before checkpointing, evidence-sensitive completion, or effects. Harness authority remains external. |
| 6 | Workspaces and locks | Added VCS-neutral registered checkouts, configurable internal CLI adapters, opt-in Git worktrees, automatic dispatch cwd selection, and exclusive resource leases. Durable creation intents, retained receipts/logs, inherited locks, and explicit outcome reconciliation prevent ambiguous creation replay. Shared locks, provider-verified receipts, and explicit cleanup tooling remain. |
| 7 | Completion evidence | Added exact criterion/revision/environment/attempt evidence coverage and file integrity checks, including first contract binding for newly produced revisions, indexed diagnostics/history, and stable recording keys. Opt-in for old workflows. Trusted command execution and mission-wide criterion-to-result mapping remain. |
| 8 | Bounded invocation context | Added snapshot watermarks, unique immutable prompt paths, prompt digests, bounded lists/text, and an explicit overflow retrieval packet. Invocation context now uses bounded SQL pages and scoped indexes; inbox pagination occurs before decoding. Full audit and explicit entity-history queries remain deliberately complete. |
| 9 | Safe planning/review commits | Added task planning keys and strict semantic manager review commits. Whole-policy and case-policy retry keys are supported. Case-local policy replacement is atomic, retains decisions/history, and refuses unresolved or cross-case work. General cross-case plan replacement remains. |
| 10 | Causal attempt audit | Added generation/revision/model/prompt provenance, attempt dispositions, resource/effect events, and recovery history. A complete causal graph and critical-path computation remain. |
| 11 | Consistent/private exports | Added one unchanged SQLite snapshot for derived views, atomic streaming publication, manifest verification, changed-artifact rejection, runtime-link omission reports, and a separate structural-only sharing path. Fine-grained redaction of useful full exports remains. |
| 12 | Migrations | Added transactional sequential upgrades and rollback/future-version rejection tests. New migrations must follow the contributor contract. |
| 13 | Adversarial tests | Added real controller-kill recovery plus claim races, stale owners/tokens, uncertain effects, migration rollback, evidence tampering, quotas, and export tests. Wider randomized fault injection remains. |
| 14 | Contributor contract | Added root AGENTS.md with state, migration, docs, tests, and release invariants. |
| 15 | Stuck-work recovery | Added bounded failed-attempt handling, recovery, durable escalation, and why diagnostics. Failure-category-specific backoff and automated repair selection remain. |
| 16 | Mission amendments | Added immutable old/new mission revisions and deauthorization of remaining work before replanning. Selective adoption and task-level objective version annotations remain. |
| 17 | Fan-out/fan-in | Existing dependency barriers now have example workflows with parallel investigations/port slices and a sole integration stage; cancellation propagates through descendants. First-class task groups and reducers remain. |
| 18 | Persistent runtime | Existing durable cases/signals/waits now have bounded `serve` polling and restart recovery. Provider-specific revision supersession and OS autostart await integration. |
| 19 | Risk-based policies | Existing policy packs and human decisions remain. Automated risk classification and provider-specific approval policy await owner scope decisions above. |
| 20 | Explanation tools | Added deterministic why/explanation output with attempts, blockers, limits, and uncertain effects in exports. Full critical paths and timeline visualization remain. |
| 21 | Evaluation loop | Integrity-checked exports and reproducible failure tests are available; scored model postmortem evaluations await a labeled dataset and model choices. |
| 22 | Templates/setup | Added performance investigation, pipeline repair, and system port templates alongside existing PR workflows, plus runtime setup instructions. An isolated demo and concise status are available; interactive harness setup remains. |
| 23 | Operator CLI | Added lifecycle, recovery, why, configure, effect, resource, workspace, evidence, amendment, review commit, serve, and audit verification commands with generated reference. |
| 24 | Budgets | Added persistent task/run/failure-attempt/deadline limits and stopping dispositions. Money/token/API/attention limits await metering integration. |
| 25 | Model escalation | Added optional attempt-based escalation_models and model provenance. Semantic/risk routing and measured cost-quality optimization remain. |

## Engineering follow-ups without owner questions

These are remaining implementation work, not decisions being pushed to the owner:

- Mission-wide criterion-to-result mapping, task-group outcomes, and cleanup
  contracts. Mission/case/workstream completion now distinguishes partial results.
- Semantic policy evaluation, general cross-case plan replacement,
  version-aware service supersession, and first-class reducer groups.
- Complete causal graphs and critical paths. Repeatable inactive-history and
  active-service benchmarks are implemented, along with bounded context/inbox
  reads and bulk reconciliation. Provider/harness load evaluation remains.
- Conditional retry/backoff, shared resource locks, granular lifecycle scope, and
  explicit workspace cleanup tooling. Creation intents and attachment recovery are implemented.
- Automatic verification of provider receipts and bounded trusted test execution.

Do not call the persistent-coworker release gate complete until its remaining
provider and lifecycle invariants have end-to-end fault-injection coverage.


The 0.11.0 continuation adds explicit workstream cancellation, shared runner/adapter
preflight validation, indexed evidence diagnostics/history, and stable evidence
recording keys. Granular pause/resume scopes and trusted verification execution
remain separate engineering work; recorded command results are still harness attestations.

## Coordination follow-through (0.13.0)

Shipped: preserved decision choices with explicit clearing; informational references;
manager attempt identities, capped backoff and explicit retry reset; staged plan
publication with continued committed work; configurable successful-review cooldown;
shared attention and one-shot aging transitions; versioned event-to-outbox routes;
quiescent task acceptance amendments; exact-scope conditional grants and explicit
waivers checked again at effect start.

The generic grant feature records trusted harness attestations. It does not supply
provider authentication, general risk classification, receipt verification, arbitrary
command execution, or production automatic-approval policy. The read-only observation
checker is an integration example. Mid-flight acceptance interruption/adoption and
policy-stage criterion overrides remain separate extensions; current amendments
require quiescence and refuse policy-owned tasks.

Owner configuration still needed before enabling production integrations:

- Notification recipients, permitted event contents, and escalation thresholds.
- Allowed grant providers/actions/resources, issuer/delegate identities, and
  which named conditions may receive waivers. Start with exact revisions and
  explicit resource lists; no wildcard class authorization is shipped.
- Representative workload measurements before changing review cooldown defaults.
- The host supervisor and restart/wakeup policy after service poll exhaustion.

These choices do not block the shipped generic coordination mechanisms. Existing
owner questions about broader automated approval, provider integration, metering,
and OS autostart remain open. A full persistent-coworker release still requires
provider-specific end-to-end fault-injection coverage.

## U11/U12 delivered in 0.14.0

Shipped: structured decision briefs with legacy/required modes and shared rendering;
continuing-permission role guidance; a provider-neutral author-to-merge pack and
bounded reference observation checker; durable commitments, required handoffs,
staged publication, exact-scope observations, signal/wait fencing, explicit adoption,
completion integration, and case/workstream/status/audit visibility. Tests include
approval with comments, revision-changing repair, grant-bound merge, and a process
failure after the fake provider applied the action.

As agreed, proposed-task external-condition gates remain deferred for downstream
work. Existing continuation tasks already support repeated external waits. A real
provider adapter, reviewer/approval rules, permitted grant issuer, named babysitting
skill, credentials, and host wake configuration remain integration choices. Core
and fake-provider tests do not claim these production integrations are installed
or validated. Generalized artifact lifecycles are outside this release.
