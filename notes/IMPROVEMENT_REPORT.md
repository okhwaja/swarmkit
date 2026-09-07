# Swarmkit 0.10.0 — local improvement report

The codebase is now on local branch **`codex/readable-reliable-swarmkit`**, with a
verified 0.10.0 release candidate and schema 11. All changes are committed locally.
**Nothing was pushed, published, or merged remotely.**

The starting point was commit `9587139`: Swarmkit 0.7.1, schema 8, 71 tests, and a
6,839-line file containing almost the entire engine. That version already had
many roadmap foundations. This pass concentrated on making those foundations
reliable, understandable, efficient, and usable through the expected journeys.
The result has **206 passing tests**, a much shorter introduction, explicit module
ownership, and substantially lower history, active-service, and review-burst overhead.
This report includes the continued pass requested after the initial 0.8.0 handoff;
the detailed work log records each tested checkpoint.

The distributable is [swarmkit-0.10.0.zip](/Users/osmankhwaja/Documents/swarmkit/dist/swarmkit-0.10.0.zip).
Start with the [README](/Users/osmankhwaja/Documents/swarmkit/README.md), the
[code map](/Users/osmankhwaja/Documents/swarmkit/docs/CODE_MAP.md), or the
[updated backlog](/Users/osmankhwaja/Documents/swarmkit/docs/ROADMAP_BACKLOG.md).

## What Swarmkit does, and what I used to judge the changes

Swarmkit coordinates an existing agent harness. A mission describes an outcome;
a manager creates tasks; fresh workers perform bounded work. SQLite preserves
the plan, evidence, questions, attempts, and external-action history when agent
conversations end. Swarmkit does not supply the model, provider credentials, or
tool permissions.

I used five practical journeys from the roadmap review:

- Investigate a performance complaint, measure it, improve it, and verify the result.
- Diagnose a pipeline failure, wait for human authority or an external job, and recover safely.
- Run a persistent reviewer that receives duplicate notifications and later updates.
- Port a system through independent tasks and a final integration/verification step.
- Pause, restart, change plans, or recover after a controller disappears.

For each, I looked for differences between what a user would reasonably expect
and what the database, subprocesses, reports, or agent prompts actually did.

## 1. Made the project easier to navigate

**Background.** The original `swarmctl.py` combined argument parsing, schema
migrations, SQL mutations, process execution, reports, and policy validation.
Finding a behavior required navigating thousands of lines, and changing a helper
could unintentionally affect distant workflows.

**Change.** The engine now lives in a flat `swarmkit/` package with explicit
modules: tasks, cases, decisions, policies, delivery, evidence, workspaces,
runtime, storage/schema, prompts/inbox, queries/views, diagnostics/audit, and setup.
The [code map](/Users/osmankhwaja/Documents/swarmkit/docs/CODE_MAP.md) explains which
file owns each responsibility and how to change durable state.

These are ordinary functions with explicit imports and SQL. I did not introduce
an ORM, dependency-injection system, dynamic plugin loader, or repository wrapper
for every entity. The command line remains the stable integration boundary.
The root file is now a 214-line entry point and compatibility import surface for
existing Python adapters. `python3 -m swarmkit` launches the same CLI.

The source and older dense tests now use a consistent 100-column format. Optional
Black/Ruff settings are in `pyproject.toml`; runtime dependencies remain limited
to the Python standard library. An import-graph check found no relative-import
cycles across the 25 package modules.

## 2. Made database operations atomic and composable

**Background.** Some helpers began or committed transactions internally. When a
larger operation used those helpers, a failure could leave a case without its
plan, commit half of a caller's plan, or leave a connection in a broken transaction.

**Change.** Database mutations share a clear transaction boundary. A standalone
operation acquires a write transaction before reading state that authorizes its
changes. A nested operation uses a savepoint, so it cannot commit its caller's
partially built plan. State changes and their audit events succeed together.
Commit failures also roll back correctly.

This makes a larger Python planning operation straightforward: wrap its domain
calls in `transaction(conn)`. If one fails, the caller can roll back the whole
plan, or catch a nested failure without losing unrelated work in the outer scope.

**Evidence.** Tests inject late event failures, quota failures, invalid policy
references, nested errors, and deferred foreign-key failures at commit. They
verify both the stored state and event history, rather than only return values.

## 3. Removed long-history overhead from agent context and inbox reads

**Background.** Prompts and inbox leases loaded large mission/event histories
before truncating the result. A small visible prompt could still require tens of
megabytes of intermediate objects. Old case signals could also crowd newer
updates out of a worker's context.

**Change.** Prompt generation now queries bounded, relevant pages directly.
Worker context includes its task, dependencies, current decisions, workspace,
evidence contract, relevant case updates, and runtime revision. Case signals are
newest first. Overflow pages include explicit retrieval instructions, and context
reduction preserves essential mission/task identity.

Inbox reads and leases apply their limit in SQL before JSON decoding. The default
page is 50 events, with a maximum of 500. Scoped offsets prevent one task's cursor
from silently advancing another scope. Schema 9 adds indexes for these lookups.

**Measured result.** With 1,000 completed tasks and 25,000 historical events:

| Operation | Before | After | Python allocation peak before → after |
|---|---:|---:|---:|
| Worker prompt | 264.387 ms | 2.014 ms | 57.91 MB → 0.170 MB |
| Manager prompt | 267.902 ms | 2.076 ms | 57.91 MB → 0.184 MB |
| 50-event inbox lease | 216.369 ms | 0.982 ms | 54.89 MB → 0.200 MB |

At ten times that history, the improved allocation peaks remained approximately
unchanged. These are local measurements under `tracemalloc`, not production
latency guarantees or total process-memory measurements. Full reports, explicit
entity histories, JSON snapshots, and private audits remain more complete reads.

The [benchmark and methodology](/Users/osmankhwaja/Documents/swarmkit/docs/PERFORMANCE.md)
are checked in. Tests separately enforce bounded reads and decoding counts without
fragile timing thresholds.

## 4. Bound human decision acknowledgements to the current attempt

**Background.** Another agent could acknowledge a decision, a replacement worker
could inherit the previous worker's acknowledgement, and a changed decision could
leave an obsolete attempt or external-wait subscription active.

**Change.** Acknowledgement requires the current live task owner. A fresh attempt
must acknowledge the current answer itself. Revising a decision or linking a new
one retires affected active attempts and obsolete waits. An executing external
action remains uncertain when its attempt is interrupted.

A withdrawn question cannot become a gate for new work. Empty questions and
answers are rejected before mutation. Late replies to withdrawn questions can
still be recorded as case evidence without reopening the old question.

**Why it matters.** In the pipeline journey, an answer such as “continue ingestion”
cannot remain privately known only to an old worker while its replacement acts
on an earlier instruction. Actual permission enforcement still belongs to the
harness and tools.

## 5. Prevented ambiguous deliveries from being sent again automatically

**Background.** A sender could exit successfully without recording a receipt, or
its lease could expire after the external service accepted the message. The old
code returned that job to the pending queue. That could send the same message
again. Timeout logging also had a bytes/string failure path, and delivery runs
did not have the same crash-liveness protection as ordinary agent runs.

**Change.** Deliveries now have an `UNKNOWN` state. Missing receipts, timeouts,
expired claims, and controller loss require provider reconciliation before another
send. `delivery reconcile` records a provider observation: `sent` closes the job;
`not-sent` makes a deliberate retry possible. A proven launch failure remains a
definitive failure.

Agent and delivery processes share a streaming subprocess helper. Logs go to
files, children inherit the ownership lock, and recovery includes delivery runs.
Delivery prompts use unique paths. Final reports can be sent after finite mission
completion, while lifecycle controls still prevent new sends when paused/cancelled.

**Evidence.** Tests kill a real controller while its sender is alive, exercise
lease expiry and timeout logs, and prove that receipts and uncertain jobs cannot
be blindly replayed. Schema 9 also identifies known ambiguous legacy errors and
moves those jobs to `UNKNOWN`.

## 6. Made lifecycle controls consistent across work types

**Background.** Pause fenced workers but allowed an old manager to commit its
review. Drain could report that work had stopped while a manager or sender was
still active. Cancelling an uncertain delivery could hide whether it had already
been sent.

**Change.** Pause retires running manager-review leases; late process exits cannot
acknowledge a replacement review. Cancel/abandon withdraw pending manager work.
Drain includes active tasks, manager reviews, claimed deliveries, and every
unclosed agent/sender process—even a sender that has already recorded a receipt.
Reconciliation records the transition to `PAUSED` only when that work has ended.
Resume and mission amendments also account for delivery liveness and uncertainty.

An in-flight or `UNKNOWN` delivery cannot be cancelled into a misleading terminal
state. Its provider outcome must be established first. The health checker now
recognizes cancelled manager reviews as a legitimate state.

## 7. Distinguished partial delivery from success and permanent cancellation

**Background.** A case containing both completed and cancelled tasks could appear
simply “done.” Cancelling intake work could prevent a replacement policy, while
cancelling a case could leave dependent tasks outside the case waiting forever.
Repeated links and follow-ups could also reopen a case or retain an old success
summary incorrectly.

**Change.** Cases and workstreams now expose `SUCCEEDED`, `PARTIAL`, or `CANCELLED`
completion outcomes separately from their lifecycle status. Finite mission
completion conservatively defaults to `PARTIAL` when planned work was cancelled.
A manager may explicitly choose an outcome with evidence explaining why a
cancelled approach does not represent missing requested work.

Task/case cancellation shares descendant propagation and retires obsolete waits.
Questions are withdrawn only when all affected work is terminal. Explicit case
cancellation remains permanent; an exhausted intake plan can be replaced. Repeated
existing links are inert, and actual follow-ups clear stale completion summaries.
Reports and boards show runtime controls and completion outcomes.

These summaries are conservative history-based signals. They are not yet a full
mission-wide mapping from each success criterion to a delivered result.

## 8. Made service and workflow retries identify the actual operation

**Background.** Follow-up deduplication searched for a signal ID inside task prose.
Editing that prose could create duplicate work; an unrelated mention could suppress
the real follow-up. Whole policy applications had no retry key, so a manager unsure
whether a command finished could create another complete workflow.

**Change.** Signals have an explicit database relationship to their wakeup task.
Migration reconstructs older relationships from structured events. An identical
retry returns the original task even after description edits or case cancellation.

`policy apply --idempotency-key` binds a request to its installed definition,
guidance, resolved variables, workstream, and authorization. Identical retries
return the same application; changed specifications under the key are rejected.
The key and task graph commit together, so a failed application does not consume
its retry identity. Existing case-open retries also remain readable after a
mission is cancelled without reopening work.

The continued pass also fixed case planning. A successful `case apply-policy`
previously rejected a retry, and replacing intake required separate cancellation
and application commands. Now `case apply-policy --replace --idempotency-key KEY
--reason TEXT` creates the replacement graph and retires unfinished old work in
one transaction. A malformed policy, quota failure, or injected late error leaves
the old plan intact. Completed results remain in history.

Open questions and resolved answers are linked to new tasks before retiring old
ones, so plan replacement does not silently withdraw human constraints. Unclosed
harnesses, uncertain effects/checkouts, and dependency descendants outside the case
prevent replacement until explicitly handled. Concurrent planners with the same
key receive one application. A retry of an older key reports that historical
application alongside the current case plan; it never reinstalls obsolete work.

## 9. Fixed inquiry and payload failure paths

**Background.** Asking about a completed service case reopened it before the
briefing task was guaranteed to exist. Failed planning could leave copied intake
payloads behind. The payload fingerprint and actual copied bytes could disagree
if the source changed between reads.

**Change.** Inquiry creation moved out of CLI routing into one domain operation.
Reopening the case, creating briefing work, and linking it now commit together.
Payload copying checks the identity used by the request fingerprint, and failed
intake commands remove only their newly created snapshots.

SQLite and files cannot share a crash-atomic transaction. A killed process or a
larger outer Python transaction rollback may still leave unregistered snapshots.
Private audits now include only intake payloads referenced by their frozen
database. Auditing does not delete live files or checkouts.

## 10. Made verification work for newly produced revisions

**Background.** Requiring every evidence contract before a claim assumed that an
implementation already knew the revision it would produce. That made an otherwise
valid strict-evidence implementation awkward or impossible to finish directly.

**Change.** A current owner may bind an initially absent contract once its exact
result revision is known. It must acknowledge current decisions first. It cannot
replace a contract already pinned for the attempt, so an independent verifier
cannot silently switch to an easier revision. Identical contract retries produce
no extra event.

Strict completion still requires successful evidence for every acceptance
criterion at the exact revision, environment, task generation, and mission
revision, with unchanged result-file hashes. Empty legacy criteria cannot pass
that gate. Revision identifiers remain opaque, including jj/internal identifiers.
The harness is still responsible for honestly executing the recorded command.

A later audit found that an old passing record could still cover a criterion
after a failed rerun. The newest record for that criterion, contracted target,
and attempt now governs coverage. A later failure blocks completion until fresh
successful evidence is recorded; results for another target do not supersede it.

Evidence and its artifact now use one file-hash observation. Previously the same
file was read twice and could change between reads, producing inconsistent hashes.
Completion rechecks each distinct result path once even when it covers several
criteria. Tests cover retained old passes, failed reruns, recovery, file mutation,
missing files, and shared result paths.

## 11. Preserved and improved VCS-neutral checkout workflows

**Background.** Your work environment uses jj and an internal lightweight-checkout
CLI. Swarmkit must not infer Git from the fact that its own source repository uses
Git. The existing provider boundary supported this, but a running owner could not
invoke its configured creator because `workspace create` lacked an owner argument.
Checkout children also lost their coordination lock when their controller died.

**Change.** `workspace create --agent` now permits the live owner and rejects stale
owners before invoking the configured CLI. The child inherits the creation lock.
Tests use source paths with spaces, an internal-style adapter, opaque revision
expressions, and a real killed controller.

The efficient integration is still a configured argv array that invokes your
internal CLI directly if it can return the small JSON receipt, or a thin adapter
that translates its output. A harness that already knows how to make checkouts
can create one and register it. No extra model invocation is required merely to
create a checkout. Git worktrees remain an explicit provider choice.

An already running harness must change to the returned checkout directory itself;
subsequent dispatches select it automatically.

The continued pass closed a more serious recovery gap. An internal CLI can allocate
a checkout somewhere other than Swarmkit's suggested path and lose its receipt.
Checking only the suggested path did not prevent a duplicate invocation. Swarmkit
now commits a durable creation record before launch, including exact argv and
persistent stdout/stderr paths. Timeouts, lost receipts, and controller loss remain
`UNKNOWN`; only a proven failure to launch is automatically retryable.

`workspace attempts` shows those records. After inspecting the provider, an operator
records `workspace reconcile --outcome created|not-created`. Reconciliation cannot
run while a surviving child retains the process lock. A valid success receipt is
saved as `CREATED` before attachment, so a later eligible owner can repeat the create
request and attach it without invoking the provider again. Registration marks it
`REGISTERED`; confirmed absence permits a new creation. No checkout is deleted.

Uncertain creation participates in drain/resume/amendment/completion checks.
Pending creation blocks worker claims before consuming an attempt. The scheduler
reports `WAITING_FOR_WORKSPACE`, and brief status supplies a recovery next step.
Dispatch rechecks the directory in its run-registration transaction, closing a
race where creation could start after the initial cwd lookup. Tests kill a real
controller, lose receipts at provider-allocated paths, expire ownership, and inject
a creation between dispatch's two reads. Automatic provider verification and
provider-specific cleanup remain integration work.

## 12. Made first use much simpler and safer

**Background.** The introduction exposed a large amount of protocol before showing
whether the project was useful. Trying it required configuration before a newcomer
could see a completed result. Initialization could overwrite an existing runner or
leave a half-created database that prevented retry.

**Change.** The README is now 124 lines organized around fit, a no-credentials demo,
three real-work setup steps, a few concepts, and focused documentation links.
`demo` performs a complete synthetic pipeline recovery with no model or provider
calls. It uses a separate default directory, ignores an inherited `SWARM_ROOT`,
and refuses to overwrite existing demo state/output.

`status --brief` gives the objective, control state, task counts, outstanding
questions, uncertainty, and a next action. Existing JSON status remains available.
`decision show` retrieves one question. Initialization constructs a complete
closed database privately, publishes it atomically under a process lock, and
preserves an existing `runner.json`.

Malformed policy/extension/workspace input now produces domain errors instead of
raw Python type/attribute/index tracebacks. New tasks require a real title,
description, and at least one nonempty criterion.

## 13. Made audit exports truthful, private when requested, and memory-conscious

**Background.** Share-safe export first wrote a full private archive and then
rewrote it. A late failure could leave the private version at the requested path.
The exporter also reconciled only its copied database, inventing transitions that
were absent from the actual mission, and read the complete ZIP back into memory.

**Change.** Export publication is atomic and preserves the previous output on
failure. Private views derive from one unchanged database snapshot. Events and
archive members stream to files. Share-safe export has a separate counter-only
path and never copies private runtime files or the database.

Manifest verification validates structure, relative paths, duplicate entries,
sizes, and streaming content hashes. Malformed archives return useful problems
instead of a traceback. Exports must be written outside the mission directory to
avoid overwriting their source. Hash verification detects content changes; it
does not authenticate the archive's author.

Copied intake payloads are now hashed after copying and compared with the frozen
case/signal record. Changed or missing bytes are omitted and explained in
`intake-export.json`. This closes a race where an archive could contain a payload
that differed from its canonical intake hash. The archive may still pass integrity
verification while reporting unavailable source evidence; the two claims are
separate. Tests mutate a payload during copying and confirm the source is retained.

## 14. Kept local runtime data out of release packages

**Background.** The ZIP builder selected matching files from anywhere under the
repository. Local mission JSON/Markdown or symlinked private content could become
part of a distribution. A failed build could overwrite an earlier valid ZIP.

**Change.** Packaging uses explicit source/documentation roots and root files,
excludes mission directories, symlinks, hidden local content, and caches, and writes
a replacement only after a successful build. ZIP timestamps and permissions are
normalized for reproducibility. `.gitignore` covers common local runtime files.

Documentation checks use the shipped file selection. They still verify links,
generated CLI help, required guidance, versions, and bundled manifests, but no
longer force an encyclopedic list of arbitrary phrases into the README.

## 15. Reduced repeated work for active services

**Background.** The first performance pass concentrated on old, completed history.
A persistent service can instead have hundreds or thousands of cases still open.
Reconciliation queried dependencies and questions separately for every candidate
and fetched each case's tasks and decisions on every poll, including completed
result text that was not needed yet.

**Change.** SQL computes task eligibility alongside dependency/decision gates and
groups case task/decision counts. It reads only the fields required for state
classification, then retrieves the newest delivered-task result when a case closes.
Human questions still take precedence over external waits and verification; mixed
completion still reports partial outcomes.

With **1,000 active cases / 5,000 tasks**, unchanged-pass reads fell from **6,009
to 9**. Full reconciliation measured **50.095 → 10.576 ms**, with Python allocation
peak **2.289 → 0.756 MB**. At 5,000 cases / 25,000 tasks, a local pass measured
63.925 ms. These are disposable-fixture observations, not production latency
promises. Regression tests check query counts and state semantics rather than timing.

## 16. Kept manager review bursts bounded and retrievable

**Background.** Every completion appended to one pending JSON review. A burst of
1,000 triggers repeatedly decoded and rewrote an ever-larger list, then asked one
manager invocation to consider all of it. An urgent repeat of an existing trigger
also failed to promote its normal-priority review. The prompt's suggested command
for retrieving reviews did not exist.

**Change.** Newly created reviews hold at most 50 triggers. Larger bursts form
serialized batches, with an indexed identity lookup that deduplicates across all
pending batches. Urgent repeats promote their existing batch. Strict review
commits still require an explicit disposition for every trigger; no trigger is
dropped. Schema 11 preserves the order and contents of legacy oversized reviews.

A 1,000-trigger enqueue benchmark measured **2.328 → 0.251 seconds**, with Python
allocation peak **1.415 → 0.126 MB**, producing 20 complete batches. This measures
coordination cost, not model review speed.

`review list` provides bounded summaries and cursor pagination; `review show`
returns every ordered trigger and any recorded semantic commit. A manager's active
review sorts before pending reviews, and its ID/retrieval command survives even
extreme prompt overflow. Tests cover migration, duplicates in an earlier full batch,
urgency, expiry, rollback, semantic coverage, pagination, and actual CLI retrieval.

## 17. Made operator reads consistent and focused

**Background.** A report uses several SQL queries. Another process could commit
between them, leaving old task state beside new case/workstream state. Reading
one task or case also regenerated whole-mission boards and reports, adding hidden
work and file writes to ordinary agent retrieval.

**Change.** Multi-query views share a read snapshot. They reuse a caller's existing
transaction without committing or rolling back its pending writes. Status-report
state, health, and failed runs are gathered together. Entity list/show commands
read one snapshot after any needed reconciliation and return their requested data;
`board` and `report` explicitly refresh derived files.

Tests commit a case cancellation halfway through snapshot construction and verify
that every field still describes the earlier state. Other tests cover nested
transaction ownership, error cleanup, report/health consistency, and absence of
unrequested report writes across fourteen read commands.

## Validation and release compatibility

The final source and newly extracted distribution each pass **206 tests** on
Python 3.9.6/macOS. The suite grew by 135 tests from the starting point. Coverage
includes real controller kills, claim/ownership fencing, transaction and commit
failure injection, timeout behavior, migration, evidence integrity, idempotency,
privacy boundaries, bounded context, and non-Git checkout adapters.

The following completed successfully:

```sh
python3 -B scripts/generate_cli_docs.py
python3 -B scripts/check_docs.py
python3 -B scripts/release_check.py
python3 -m black --check swarmctl.py swarmkit scripts tests examples/demo_lifecycle.py
ruff check swarmctl.py swarmkit scripts tests examples/demo_lifecycle.py
```

Black checked 56 Python files across source, examples, scripts, and tests.
Ruff reported no configured F-class issues. A real
schema 8 fixture created by the original 0.7.1 code upgraded successfully: it
preserved an opaque checkout revision, reconstructed a signal link, backfilled
partial completion, fenced an ambiguous delivery, passed `doctor`, and produced
a verified audit. That same fixture was advanced through schema 11 during the
continued pass; `doctor` and audit verification passed again.

A final measurement at `c31d77d` reconfirmed the improvements: worker and manager
prompts measured 2.154/2.152 ms with 25,000 historical events; active-service
reconciliation measured 10.279 ms with 1,000 open cases; the 1,000-trigger review
burst measured 0.252 seconds. These are medians of three disposable-fixture samples.

**Upgrade deliberately:** stop old controllers and keep a pre-upgrade backup.
Opening an existing mission with 0.10.0 upgrades it sequentially to schema 11;
older releases cannot read that schema. Existing Git registrations remain intact,
and no target checkout is converted or cleaned up. The command reference, runtime guide,
changelog, examples, and package version agree on 0.10.0. Additional migration
tests preserve schema-9 workspaces and schema-10 review payloads/identities.

## What remains, and what needs your input

The [backlog](/Users/osmankhwaja/Documents/swarmkit/docs/ROADMAP_BACKLOG.md) separates
owner decisions from engineering work. I did not infer answers while you were away.
The owner decisions are production auto-review scope/risk thresholds, the first
provider/action integration, autostart host/OS preferences, metered usage limits,
and a labeled model-evaluation dataset.

Engineering follow-ups include provider-verified receipts and cleanup tooling,
finer lifecycle scopes, general cross-case plan replacement, explicit reducers/task
groups, mission-wide criterion mapping, and complete causal/critical-path views.
Durable checkout creation/attachment recovery, atomic case-local policy replacement,
and active-service/review-burst benchmarks are now implemented. No production
provider integration, automatic approval policy, OS autostart service, or live AI
quality evaluation was installed or claimed complete.

The implemented portions are tested local coordination behavior. The benchmarks
cover inactive history, active cases, and review bursts, but not every workload.
Full private reports/exports can still grow with mission size. Actual external authority, provider correctness,
and honest command execution remain integration responsibilities.

## Local commit navigation

| Commit | Area |
|---|---|
| `05cb4cc` | Atomic domain operations and module separation |
| `9a6bff5` | Bounded inbox and prompt reads |
| `59885ff` | Decision/attempt fencing |
| `e8521ef` | Delivery uncertainty and process recovery |
| `d956171` | Partial completion and case cancellation |
| `409816f` | Distribution privacy and deterministic packaging |
| `faa1b64` | Initialization, demo, brief status, and onboarding |
| `1362a64` | Workflow keys and signal identity |
| `35b6319` | Consistent, atomic, streaming audit export |
| `c9853a9` | Manager/delivery lifecycle boundaries |
| `5685062` | Atomic inquiries, payload identity, and failed-intake cleanup |
| `415a573` | Active-owner checkout creation and inherited checkout locks |
| `0b5dd36` | Dynamic first evidence contracts and input validation |
| `3fb2ea8` | Empty/withdrawn decision validation |
| `c133792` | 0.8.0 release metadata, readable tests, benchmark, and upgrade guidance |
| `1f1c6ce` | Initial full report and handoff |
| `6de2fbc` | Durable checkout creation and provider reconciliation |
| `d56d0c1` | Atomic case policy replacement and case planning retry identity |
| `5b2fe6f` | Bulk active-service reconciliation and benchmark |
| `abad367` | Bounded review batches, review retrieval, and checkout dispatch fencing |
| `b9ba821` | Latest verification results and copied-intake integrity |
| `c31d77d` | Consistent operator snapshots and focused entity retrieval |

This report covers the complete local improvement pass through the checkpoints above. The detailed
[work log](/Users/osmankhwaja/Documents/swarmkit/notes/IMPROVEMENT_WORKLOG.md) preserves
intermediate findings and verification history.
