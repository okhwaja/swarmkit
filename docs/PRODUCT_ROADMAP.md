# Swarmkit product roadmap

Status: P0 and P1 direction approved; P2 deferred

Implementation coverage and outstanding decisions: [ROADMAP_BACKLOG.md](ROADMAP_BACKLOG.md).

This roadmap describes the product capabilities Swarmkit should support to act
as a dependable coworker for both transient and persistent engineering work. It
is a planning artifact, not documentation of currently implemented behavior.
The authoritative descriptions of current behavior remain the documents listed
in `docs/DOCUMENTATION_POLICY.md`.

## Product goal

A user should be able to give Swarmkit an ambiguous objective, define the
system's authority and stopping conditions, and trust it to make bounded
progress over minutes, days, or weeks. Work may cross process and machine
restarts, wait on humans or external systems, fan out across agents, and end in
success, a useful partial result, or a clearly explained escalation.

The platform should provide general coordination primitives rather than
hard-code individual workflows. Performance investigations, pipeline repair,
pull-request review, and software ports should be compositions of the same
mission, task, attempt, wait, decision, authority, evidence, and event model.

## Ranking method

Items are stack-ranked globally. A lower rank means the item should be addressed
first. The ranking weighs:

1. Risk of irreversible, duplicated, lost, or falsely completed work.
2. How many customer journeys depend on the capability.
3. Whether later roadmap items require it as a foundation.
4. Frequency and severity of the failure it prevents.
5. Value delivered relative to implementation complexity.

Phases are directional:

- **P0 — Trustworthy unattended execution:** required before treating a swarm as
  a persistent coworker.
- **P1 — Coworker product experience:** makes the safe kernel productive and
  understandable across common workflows.

## Current scope boundaries

- Swarmkit records that an agent needs confirmation, durably pauses the related
  work, routes the question, records the answer, and resumes the correct work.
  The harness and the tools it exposes remain responsible for enforcing which
  actions and credentials an agent can actually use.
- The current product is for one user running Swarmkit on one host. Multi-host
  scheduling and organization-level portfolio governance are out of scope.
- P0 and P1 are the approved roadmap. P2 is deferred and is not included in the
  active stack ranking.

## Customer journeys the platform must enable

| Journey | Expected flow | Acceptable stopping points |
|---|---|---|
| Improve a slow system | Establish a reproducible baseline; fan out profiling and hypotheses; rank findings; implement candidates in isolated workspaces; compare benchmarks; prepare a PR or CL with evidence. | Verified improvement; no safe improvement found; blocked on representative data; agreed budget exhausted. |
| Restore a broken pipeline | Capture incident state; separate diagnosis, mitigation, and repair; request approval for risky actions; execute with receipts; observe healthy runs; record a postmortem. | Restored and verified; mitigated but not repaired; waiting on an owner or vendor; human escalation required. |
| Continuously review PRs | Create or update a case per PR revision; deduplicate triggers; apply review policy; inspect and test the exact head revision; comment, approve, or escalate within granted authority; invalidate stale reviews. | Approved; feedback posted; held for human review; obsolete because the PR changed or closed. |
| Port a system from A to B | Inventory behavior and compatibility requirements; create a user-journey test matrix; partition work; integrate through explicit fan-in; verify the final revision; prepare a PR. | PR ready; useful partial port with documented gaps; blocked by an ambiguous specification or unsupported behavior. |
| Pause, restart, and change course | Stop new claims; drain or checkpoint active work; persist external waits and uncertain actions; resume after a process or machine restart; amend the objective without erasing history. | Safely paused; resumed; cancelled with cleanup; awaiting operator reconciliation. |

## Stack-ranked roadmap

| Rank | Phase | Capability | What this enables | Consequence if omitted |
|---:|---|---|---|---|
| 1 | P0 | Crash-safe attempts and controller recovery | Swarms can continue after a laptop reboot, process crash, harness timeout, or machine replacement without losing track of active work. | Tasks can remain permanently claimed, completed work can be rerun, and users may need to inspect or edit the database before work can continue. A persistent swarm would be less reliable than a human coworker. |
| 2 | P0 | Safe tracking of real-world actions (effect ledger) | Swarmkit can safely retry or reconcile actions that change another system, including approving a PR, merging code, restarting a pipeline, deploying, or sending a notification. | If a machine crashes after sending a request but before saving the response, Swarmkit cannot know whether it happened. Retrying may perform the action twice; not retrying may silently lose it. |
| 3 | P0 | Pause, drain, resume, cancel, and abandon | Users can stop new work immediately, let selected in-flight operations finish safely, resume later, or permanently cancel work while retaining its history. | The only practical stop control is killing processes. That can leave half-finished changes, and restarting may unexpectedly continue work that the user intended to stop. |
| 4 | P0 | Leased inbox delivery with explicit acknowledgment | Agents reliably receive plan changes, decisions, findings, and external signals even when they crash while processing them. | An agent can mark a message read before acting and then crash, causing the update to be lost. Naive redelivery can instead apply the same plan change twice. |
| 5 | P0 | Durable confirmation waits and resume | An agent can pause before an action that needs explicit confirmation, explain exactly what it wants to do, and resume the correct task after you approve or reject it—even if the agent, harness, or machine restarts while waiting. The harness and tools continue to enforce what actions are actually available. | Approval may exist only in a transient conversation. After a restart, the question or answer can be lost, the task can wait forever, or the wrong attempt can consume an old approval. You would have to rediscover and manually reconnect pending confirmations to work. |
| 6 | P0 | Separate workspaces and locks for shared resources | Multiple agents can safely change code and use staging systems, devices, pipeline controls, or other scarce resources in parallel. | Agents can overwrite each other's files, test a moving checkout, restart the same pipeline twice, or invalidate each other's environment. Correct individual work can combine into a wrong result. |
| 7 | P0 | Evidence-backed completion contract | Users can trust that a claimed result was actually tested against every requested outcome on the exact code and environment being delivered. | An agent can say "tests pass" based on incomplete checks, an older commit, or the wrong environment. Broken work may be presented for review or automatically approved. |
| 8 | P0 | Immutable, bounded invocation context | Missions and recurring services can run for weeks while each agent receives a small, coherent, reproducible packet containing exactly the state relevant to its assignment. | Prompts grow without bound, costs rise, important facts disappear inside noise, smaller models fail more often, and two agents may act from inconsistent snapshots. |
| 9 | P0 | Idempotent planning and semantic manager review commits | Managers can safely replan after new evidence or retry after a crash without duplicating tasks, and the system can prove every review trigger was considered. | Retries may create duplicate work, while a manager process can exit successfully without responding to a finding or decision. Important information can be silently treated as reviewed. |
| 10 | P0 | Causal, attempt-level audit model | Operators can reconstruct why work happened, identify whether planning, delegation, execution, verification, or the harness failed, and compare attempts and models fairly. | The archive shows only a loose chronology. Postmortems must guess which input caused an action, which attempt produced evidence, and which subsystem deserves remediation. |
| 11 | P0 | Consistent, integrity-checked, privacy-aware exports | Users can share a trustworthy run bundle with a reviewer, another model, or an incident process without exposing unrelated secrets or presenting contradictory evidence. | Different files in one archive may describe different moments, changed artifacts may look valid, and prompts or logs may leak credentials, customer data, or local paths. |
| 12 | P0 | Sequential, transactional schema migrations | Existing long-running swarms can upgrade to new Swarmkit releases without losing their history or becoming incompatible. | A release that changes storage can corrupt data, silently label an old database as current, or make an active mission impossible to resume. Users may be forced to stay on old versions. |
| 13 | P0 | Adversarial lifecycle and concurrency test suite | Maintainers can change the scheduler and state model while continuously proving recovery, deduplication, fencing, and audit invariants under realistic failures. | Safety bugs appear only during real crashes, races, and long-running missions, where they are expensive to reproduce and may affect external systems. |
| 14 | P0 | Agent contributor contract | Fresh coding agents can safely implement and review Swarmkit changes without first reverse-engineering undocumented architecture and release rules. | Agent-authored changes may violate canonical-state rules, edit generated files incorrectly, omit migrations or documentation, and still appear locally plausible. |
| 15 | P1 | Supervisor and stuck-work recovery | Swarms can detect non-progress and autonomously choose a bounded retry, replan, cleanup, wait, or human escalation. | Work can remain stuck forever or retry forever while consuming resources. Users must repeatedly inspect state to learn that the swarm needs help. |
| 16 | P1 | Mission amendments and versioned replanning | Users can change goals, constraints, priorities, budgets, or approval boundaries while preserving useful work and an explainable history. | Users must either restart from scratch or edit the current plan in place. Restarting wastes work; in-place mutation lets obsolete tasks publish results against a goal that no longer exists. |
| 17 | P1 | Structured fan-out and fan-in | Large investigations and ports can divide work across many agents and combine results through a predictable reducer instead of overloading the manager. | Agents duplicate investigations, modify overlapping areas, report contradictions without resolution, and create a trigger storm. Manager context becomes the bottleneck that erases the benefit of parallelism. |
| 18 | P1 | Persistent service runtime | Recurring coworkers such as PR reviewers and monitors can react continuously, survive restarts, and track each external object revision independently. | A cron-like wrapper may miss or duplicate triggers, approve an obsolete PR revision, lose pending cases on restart, or overwhelm an external API. |
| 19 | P1 | Policy packs for risk-based autonomy | Teams can automatically approve routine, well-evidenced actions while routing risky or unfamiliar cases to a human under a reviewable policy. | Autonomy boundaries remain scattered across prompts and agent judgment, producing inconsistent decisions that are difficult to audit and unsafe to expand. |
| 20 | P1 | Deterministic postmortem and explanation tools | Operators can obtain a factual timeline, critical path, failed attempts, waits, and missing evidence immediately, before asking a model for interpretation. | Every incident requires manual database and log inspection, while model-generated explanations may confuse guesses with facts or blame the wrong subsystem. |
| 21 | P1 | Postmortem evaluation and improvement loop | The team can measure whether inexpensive models understand exports, compare model or harness versions, and turn recurring failures into tested product safeguards. | The system collects telemetry without learning from it. Postmortems may sound convincing but remain unmeasured, and recurring failures lead to more prompt prose instead of enforceable fixes. |
| 22 | P1 | Workflow templates and guided setup | New users can start performance investigations, incident repair, ports, PR review, and monitoring without designing a swarm protocol from scratch. | Each user invents different task, approval, evidence, and stopping conventions. Setup is slow, unsafe defaults spread, and workflows cannot share improvements. |
| 23 | P1 | State-aware CLI and operator experience | Humans and smaller models can understand current state and take the next safe action without memorizing protocol details or assembling long commands. | Recovery is slow and error-prone, agents waste context rediscovering identifiers, and a correct backend still feels opaque or requires an expert operator. |
| 24 | P1 | Budgets, quotas, and stopping policy | Users can delegate open-ended work while bounding money, compute, wall time, external API usage, fan-out, retries, and requests for human attention. | A swarm can remain technically active while spending indefinitely or generating unlimited tasks and approvals. Stopping depends on a user noticing the runaway behavior. |
| 25 | P1 | Model routing and escalation | Routine structured work can use cheaper models while ambiguous, contradictory, or high-risk work escalates to a more capable model with full provenance. | Using only a frontier model is unnecessarily expensive; using only a smaller model lowers completion quality and may let difficult tasks fail repeatedly without escalation. |

## Cross-cutting terminal outcomes

Every mission, workstream, task group, and persistent-service case should finish
with a typed outcome rather than relying on a generic `DONE` state:

| Outcome | Meaning |
|---|---|
| `SUCCEEDED` | All required criteria are satisfied by current evidence. |
| `PARTIAL` | A useful bounded result exists, with unmet criteria explicitly listed. |
| `BLOCKED` | Progress requires external state or authority, represented by a durable wait or decision. |
| `BUDGET_EXHAUSTED` | A configured time, cost, attempt, or attention boundary was reached. |
| `CANCELLED` | A user or policy intentionally stopped the work and cleanup was performed or recorded. |
| `ESCALATED` | The system determined that continuing autonomously would be unsafe or ineffective. |

## Roadmap-level success measures

| Measure | Why it matters |
|---|---|
| Safe restart rate | Measures whether persistent work survives ordinary infrastructure failure. |
| Duplicate external effect rate | Exposes the most dangerous retry failure. The target should be zero in tested integrations. |
| Criterion evidence coverage | Prevents claimed completion from outpacing proof. |
| Verification escape rate | Measures results later found invalid despite being accepted. |
| Median time from stuck detection to safe disposition | Measures whether the supervisor turns failures into action rather than noise. |
| Pause-to-quiescence time | Measures operational control during incidents or plan changes. |
| Context bytes or tokens per active case age | Detects context rot in persistent services. |
| Postmortem supported-claim and attribution score | Measures whether exports can drive trustworthy learning with lower-cost models. |
| Unattended useful-outcome rate by journey | Captures success, partial results, and high-quality escalation rather than rewarding only `DONE`. |
| Agent-authored change first-pass rate | Measures whether repository guidance and invariants are sufficient for safe agent-only development. |

## Sequencing guidance

Ranks 1 through 14 are a release gate for calling Swarmkit a persistent coworker.
They should be implemented as vertical safety slices: schema and invariant,
operator behavior, documentation, fault-injection test, and audit representation
in the same change.

P1 workflow templates should be built only on these primitives. For example, an
automatic PR reviewer should use the general confirmation, evidence, revision,
effect, service-case, and policy models; it should not introduce a separate
approval mechanism.

P2 is intentionally deferred. Multi-host scheduling, organization-level
governance, and fleet-wide analytics should be reconsidered only if the product's
single-user, single-host scope changes.
