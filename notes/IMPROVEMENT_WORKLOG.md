# Local improvement work log

Started: 2026-09-07 04:17:44 UTC. Allowance ends: 2026-09-07 16:17:44 UTC.
Branch: `codex/readable-reliable-swarmkit`. Do not push, open a PR, or merge remotely.
Baseline: main at 9587139, Swarmkit 0.7.1/schema 8, 71 tests, 6,839-line CLI/engine.

## Intended work

1. Reproduce lifecycle, transaction, restart, completion, and service-intake holes.
2. Fix invariants with focused regression tests and an explicit transaction boundary.
3. Separate storage/domain/runtime/presentation/CLI responsibilities into ordinary
   modules; preserve command compatibility without frameworks or dynamic dispatch.
4. Bound prompt/inbox reads at the database, measure scale, and add regression checks.
5. Make the first-use path obvious: fit, examples, a safe demo, setup, run, inspect,
   wait/answer/resume, and honest operating limits. Reduce documentation duplication.
6. Exercise the expected performance, incident, review, port, and restart journeys;
   improve primitive gaps rather than hard-coding a provider or workflow.
7. Strengthen contributor guidance, packaging, and local release checks.
8. Leave a full newcomer-friendly report with motivations, implementation,
   evidence, limitations, and local commit navigation.

## Observations to investigate (not yet confirmed)

- Atomic decorators coexist with helpers that commit or begin transactions internally.
- Case creation and policy/task attachment occur in separate commits.
- Prompts materialize entire mission/case/event histories before truncation.
- A reported DONE result may mask cancellation/partial work or stale decisions.
- Recovery, manager-review completion, and pause/drain differ between manual and runner paths.
- Checkout registration needs actual workspace context passed to agents, not just cwd.
- CLI and README expose too much protocol before showing a simple useful first run.

## Validation and progress

- Baseline release check started; results in /tmp/swarmkit-improvement-baseline.log.
- Documentation impact: CLI/state, user journey, harness, setup, architecture,
  role behavior, migrations/release metadata.

- Baseline release check passed: 71 tests in both source and extracted package.
- Reproduced six transaction/lifecycle failures. Domain operations now share one
  atomic boundary, using savepoints under an existing transaction. Failed case
  planning and failed signal wakeups leave no partial database state. Cancelled
  cases reject task links, policy application, and wakeups.
- Split the engine into explicit modules with no import cycles, keeping existing
  commands and root Python compatibility imports. Added `python3 -m swarmkit`.
- Temporary formatter installed only under /tmp; no runtime dependency added.
- Added `docs/CODE_MAP.md` to explain module ownership and transaction rules.

- Saved local commit 05cb4cc for transaction fixes/module split. Release checks
  passed 77 tests in source and extracted package. Nothing pushed.
- Inbox reads now page within SQL. A 5,003-event regression workload decoded only
  7 events for a 7-event lease. Scope expansion uses a CTE, not a Python list of
  bound IDs. Plain reads honor --limit; legacy advancement uses scoped offsets.
- Prompts no longer build full mission snapshots for each worker. Added bounded
  context pages, newest-first case signals, checkout/evidence/runtime context, and
  progressive size reduction that retains the primary task and mission.
- Added schema 9 indexes for context/event relations. No history is discarded.
- Lease timestamps now use the same sortable UTC format; nonpositive renewals
  are rejected. Transaction commit failures also roll back pending writes.
- Current focused/full source checks: 91 tests passing. Broader release validation
  will repeat after the next feature group.

- Saved local commit 9a6bff5 for bounded inbox/context reads; release check passed
  91 tests in source and extracted package.
- Reproduced and fixed five decision-fencing gaps: nonowners could acknowledge;
  a new attempt inherited an old agent's acknowledgement; revised/newly linked
  decisions left old attempts RUNNING; revisions left obsolete waits active;
  executing effects were not made uncertain on decision change. All 96 tests pass.
- Upcoming journey audit findings: mixed cancelled/completed case tasks can be
  labeled DONE without a partial outcome; auto-cancelled intake conflicts with
  applying a replacement policy; delivery subprocesses need the same liveness
  and uncertain-result handling as ordinary harness runs. These are not fixed yet.

- Saved local commit 59885ff for decision attempt fencing (96 passing source tests).
- Reproduced delivery clean-exit replay, lease-expiry replay, timeout byte/string
  logging failure, and controller-crash liveness omission. Implemented UNKNOWN
  delivery state, provider reconciliation command, shared streaming process helper,
  inherited delivery process locks, delivery recovery, and unique delivery prompts.
- Final reports can be sent after finite task completion, while pause/cancel still
  stops new delivery claims. Existing ambiguous delivery error markers upgrade to
  UNKNOWN in schema 9. Added provider-reconciliation and upgrade tests.
- Ran temporary Ruff static checks; removed unused imports from the module split.
  Runtime remains standard-library only. Source suite passed 103 before the last
  migration regression was added; full validation follows.

- Saved local commit e8521ef for delivery recovery; source/package release checks
  passed 104 tests, including real delivery-controller kill and child-lock recovery.
- Added explicit case/workstream completion_outcome, conservative PARTIAL mission
  completion (with an explicit manager override), and outcome/control visibility in
  boards/reports. Schema 9 backfills old terminal outcomes and preserves explicit
  cancellations. Eight initial completion regressions reproduced seven failures;
  all now pass, plus four additional outcome/late-reply/empty-completion checks.
- Cancellation now shares dependency propagation across tasks and cases, closes
  obsolete wait subscriptions, and withdraws questions only when all affected work
  is terminal. Explicit case cancellation is permanent; cancelling an intake task
  can be followed by a replacement policy.
- Repeated case-task links preserve completed state. Follow-ups clear stale result
  summaries. Completed cases are no longer rescanned by every reconciliation.

- Saved local commit d956171 for completion/case lifecycle; source/package release
  checks passed 116 tests.
- Reproduced distribution inclusion of local .swarm JSON/Markdown and symlinked
  private content. The builder now uses explicit source roots/files, prunes runtime
  directories, streams file content, normalizes ZIP metadata, and atomically
  replaces the output only after a successful build. Added .gitignore defaults.
- Documentation checks now inspect shipped Markdown and generated CLI/contracts,
  without forcing an encyclopedic list of arbitrary phrases into the README.
  This prepares the shorter first-use documentation pass.

- Saved local commit 409816f for packaging; 120 source/package tests passed.
- Reproduced five initialization bugs, then added private database staging, atomic
  schema/mission creation, initialization locking, objective validation, and runner
  configuration preservation. Six initialization regressions now pass.
- Added an isolated harness-free demo, bounded human-readable status, and decision
  lookup. Preserved JSON status and the existing demo script. Three first-use tests
  cover active-environment isolation, repeated demo refusal, bounded status, and
  visible human decisions/pause.
- Rewrote README around fit, a runnable demo, three real-work steps, core concepts,
  VCS-neutral checkouts, and focused documentation links.

- Saved local commit faa1b64 for first use; 129 source/package tests passed.
- Added policy application retry keys bound to manifest, guidance, resolved
  variables, workstream, and authorization. Failed transactions do not consume keys;
  identical retries return existing work after lifecycle changes.
- Replaced description-LIKE signal deduplication with a signal/task foreign-key
  relation. Migration reconstructs links from structured events. Six new tests
  cover policy retries/conflicts/rollback and signal edits/false matches/migration.

- Saved local commit 1362a64 for service/workflow retry identity; 135 tests passed.
- Reproduced private-first share-safe export, output clobber on late failure,
  unrecorded reconciliation in the exported snapshot, whole-ZIP memory loading,
  and malformed-manifest tracebacks. Exports now stage once, stream content, keep
  canonical history unchanged, and atomically publish. Share-safe queries only
  allowlisted counters. Five regressions pass; full source suite passes 140 tests.

- Saved local commit 35b6319 for audit fixes; 140 source/package tests passed.
- Lifecycle audit found unfenced manager commits after pause, cancelled reviews
  completing as DONE, drain overlooking manager/delivery ownership, and delivery
  cancellation hiding an in-flight/unknown outcome. Added unified active-run/work
  queries, manager lease retirement, deterministic drain completion, and delivery
  reconciliation guards. Six targeted regressions cover these boundaries.

- Saved local commit c9853a9 for lifecycle boundaries; 146 source/package tests passed.
- Moved inquiry creation out of CLI routing into an atomic domain operation. A
  failed quota/dependency check no longer reopens a completed case. Added two tests.
- Reproduced payload fingerprint/copy races and leaked snapshots after failed
  case policy/signal wakeups. Added scoped new-file cleanup, checked snapshot
  identity, and removed a redundant uniqueness read under the write lock.
- Existing case retries survive terminal mission state without reopening work.
  Audit intake copies now select only canonical payload references. Seven added
  tests cover these behaviors; all 153 source tests pass.

- Saved local commit 5685062 for atomic intake and inquiries; 153 source tests passed.
- Reproduced missing active-owner checkout creation and lock loss after killing
  the creator. Added workspace create --agent, pre-launch ownership checks, and
  inherited checkout locks. Tests use an internal-style adapter with opaque jj
  revisions and a real killed controller. Git remains explicitly selected only.

- Added a disposable, repeatable standard-library benchmark. Against 9587139 on
  1,000 completed tasks/25,000 events, worker context improved 264.387→2.014 ms,
  manager context 267.902→2.076 ms, inbox lease 216.369→0.982 ms under tracemalloc.
  Python allocation peaks fell from 55–58 MB to about 0.2 MB. At 10× history,
  improved prompt/inbox peaks remained stable. Method and limits are documented
  in docs/PERFORMANCE.md; raw measurement output remains in /tmp.

- Saved local commit 415a573 for checkout creation ownership/liveness; 155
  source/package tests passed.
- Implementation output revisions are often unknown before a claim. Current
  owners may now bind the first evidence contract, while existing pinned targets
  remain immutable during an attempt. Identical retries are inert; stale owners
  cannot bind. Added strict-mode end-to-end completion and legacy-empty-criteria tests.
- Malformed manifest values previously raised raw TypeError/AttributeError/
  IndexError exceptions; validation now returns domain errors. New tasks reject
  blank goals/criteria. Amendment also waits for sender runs and uncertain
  deliveries. All 164 source tests pass after these changes.

- Formatting pass made older dense tests follow the same 100-column style as the
  modules. Optional Black/Ruff configuration keeps runtime dependency-free and
  exempts only the intentional compatibility re-exports from unused-import checks.
- Final consistency review found the manager-review state validator missing the
  new CANCELLED state; corrected it and asserted doctor health after cancellation.
- Tested a real schema 8 database created with the archived baseline code. Upgrade
  preserved jj/internal workspace identity, backfilled partial completion and
  signal links, migrated ambiguous delivery state, passed doctor, and exported a
  hash-verified audit.
- Preparing version 0.8.0/schema 9 with synchronized changelog, generated CLI,
  benchmark methodology, and a current backlog rather than overstating completion.

- Final decision review reproduced empty blocker/answer acceptance and reuse of a
  withdrawn question as a gate for new work. Those inputs are rejected without
  mutation; historical idempotent links remain readable. Three regressions added.

- Final source and extracted-package release checks pass 167 tests each on Python
  3.9.6/macOS. Black checks all 51 Python files; Ruff finds no F-class issues.
  Static module graph inspection finds no relative-import cycles across 25 modules.
- Built the local dist/swarmkit-0.8.0.zip artifact. No remote operation was used.
- Saved local commit 3fb2ea8 for empty/withdrawn decision validation. Preparing the
  release/documentation/formatting commit, followed by the local handoff report.

- Saved c133792 as the tested 0.8.0 release/documentation/formatting commit.
- Completed notes/IMPROVEMENT_REPORT.md: newcomer-friendly context and implementation
  for each change, journey rationale, exact validation/measurement limits, upgrade
  guidance, unresolved integrations, and local commit navigation. Its links resolve.
- Final handoff is reporting-only under notes/, excluded from distribution; shipped
  source remains the version that passed 167 tests in both source/package checks.
  All work stayed on codex/readable-reliable-swarmkit; nothing was pushed remotely.

## Continued pass: durable checkout creation (0.9.0 / schema 10)

The user requested continued work after the initial 0.8.0 report. A provider can
allocate a checkout outside the suggested path and then lose its receipt. The
previous path-existence check could not stop a later duplicate invocation.

Added a committed creation journal before subprocess launch, retained argv/logs,
UNKNOWN/CREATED/REGISTERED/NOT_CREATED outcomes, provider-observation reconciliation,
and replay-free attachment of success receipts after pause/ownership loss. Process
locks fence reconciliation while a surviving child remains alive. Uncertain
creation participates in drain/resume/amendment/completion gates; pending attachment
blocks dispatch into the default source directory. Inspection appears in CLI,
why/doctor, and bounded task/manager context. Manual/jj/internal environments retain
opaque revisions and paths; no Git inference or automatic cleanup was introduced.

Documentation impact: CLI/state, user journey, harness/provider contract, runtime
architecture, migration/release. Schema 10 is additive. Initial full source check:
174 tests passed, including seven additional recovery/failure/lifecycle tests;
source formatting, Ruff, generated CLI and docs checks passed. Full extracted
release verification follows before the local checkpoint.

## Continued pass: atomic, retriable case plans

The case-policy path rejected a retry after successful application and required
separate cancellation/apply commands when replacing intake. A crash or invalid
replacement could strand a case between plans. Added explicit case planning keys
using existing policy-key storage, shared canonical policy request preparation,
and atomic `case apply-policy --replace --idempotency-key --reason`. Replacements
retain completed work, carry open/resolved decisions to new tasks, and refuse
external dependency cancellation or unclosed case harness/effect/checkout work.
Older request retries report their application alongside current case state;
they cannot reinstall superseded work. Nine focused tests cover concurrent
planners, injected failure after cancellation, validation/conflicting keys,
decision inheritance, external dependencies, effect/run guards, and CLI usage.
Documentation impact: planning/state/CLI and service user journey; no new schema.
Checkout checkpoint 6de2fbc passed all 174 source/extracted-package tests.

## Continued pass: active-service reconciliation

Built a provider-free service fixture to measure 1,000 active cases / 5,000 tasks.
The prior poll made 6,009 read statements by separately querying every candidate's
dependencies/decisions and each case's tasks/decisions. Replaced these with SQL
eligibility predicates and grouped case counts, projected only needed columns,
and read a completed result only when the case closes. Read statements fell to 9,
full median 50.095→10.576 ms, Python allocation peak 2.289→0.756 MB. Added semantic
state-precedence tests and a hardware-independent constant-query-count test.
Documentation impact: performance/architecture and release metadata; public
state semantics retained, with deterministic most recently created delivered-task
result selection at case closure. Case plan checkpoint d56d0c1 passed 183 tests
in source and extracted distribution.

## Continued pass: bounded manager review bursts (0.10.0 / schema 11)

A burst of 1,000 completions built one 1,000-trigger JSON review, repeatedly
decoding/rewriting the growing list. New reviews now cap at 50 triggers; schema 11
adds an identity index for cross-batch pending deduplication and preserves ordered
legacy payloads. Duplicate urgent observations promote their existing batch.
The same burst benchmark measured 2.328→0.251 seconds and 1.415→0.126 MB Python
peak, retaining 20 batches / all 1,000 triggers.

The burst review also exposed an invalid `manager review list` retrieval hint and
a normal running review that could be crowded out by urgent pending batches.
Added actual `review list` summaries with cursor pagination and `review show` for
complete ordered triggers/semantic commits. Prompt overflow retains current_review
identity and retrieval command, and running reviews sort first. Tests cover batch
size, cross-batch dedupe, urgency promotion, all-trigger semantic commits, expiry,
rollback, schema-10 migration, CLI paging, valid retrieval hints, and overflow.
Documentation impact: runtime/review state, agent interface/role guidance, CLI,
performance, migration/release. Prior service checkpoint 5b2fe6f passed all 186
source/extracted-package tests.

Checkout handoff review found a second-read race: dispatch resolved its cwd before
its write transaction. A provider creation beginning in that interval could leave
it launching against the default source. Added a shared cwd check inside run
registration and fault injection between the two reads. Pending creation now
blocks claims before generation allocation, and the scheduler reports
WAITING_FOR_WORKSPACE instead of repeatedly consuming failed worker attempts.
The expired-owner recovery test now attaches its durable receipt before claiming
the next attempt. Seventeen workspace tests pass; the prior bounded-review-only
release check passed 193 source/extracted-package tests.
