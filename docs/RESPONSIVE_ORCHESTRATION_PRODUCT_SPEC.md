# Product spec: responsive, evolving swarm execution

Status: proposed
Audience: Swarmkit maintainers and implementation owner

## Product summary

Swarmkit should manage ambiguous work as an evolving process rather than a
sequence of rigid batches. It should react promptly when an agent discovers a
valuable new line of inquiry, continue using available capacity while other
tasks run, and represent long periods of external waiting without keeping an
agent occupied.

## Problem

Ambiguous missions rarely unfold according to a complete plan established at
the beginning. Agents search, test assumptions, make changes, and uncover new
information. A useful discovery may justify a follow-up question, invalidate
planned work, or reveal an entirely new outcome that deserves its own
workstream.

Swarmkit's current execution model responds at worker-wave boundaries. The
manager launches before a group of tasks, then does not run again until every
agent in that group exits. This produces two user-visible problems:

1. A fast, important result can sit unreviewed while an unrelated task continues
   for a long time.
2. A task that is mostly waiting for an external system can occupy an agent and
   a concurrency slot for hours.

For example, one agent may answer "can this code support X?" in five minutes
while another waits several hours for a pipeline run. The first result should be
able to change the plan immediately, and the pipeline wait should not consume an
agent for those hours.

## Target users

- Operators assigning ambiguous, multi-step missions to Swarmkit.
- Managers who need the swarm to adapt as evidence arrives.
- Workers that discover consequential information outside the narrow answer to
  their current task.
- Harness integrators running missions that include CI, pipelines, imports,
  deployments, or other long external operations.

## Jobs to be done

When an agent finishes useful work quickly, I want the swarm to use that result
without waiting for unrelated work, so the mission continues at the speed of
the available evidence.

When an agent finds something that may warrant follow-up, I want that discovery
reliably elevated to the manager, so it is explicitly incorporated, deferred,
or dismissed rather than lost in prose.

When the mission depends on a long-running external job, I want Swarmkit to wait
durably without holding an agent open, so capacity and cost remain proportional
to actual work.

When I inspect the mission, I want to understand what is actively being worked,
what is waiting, what new findings need triage, and what will cause progress to
resume.

## Product principles

### The plan is expected to evolve

Discovery is part of execution, not merely a preliminary phase. The manager may
add, remove, or redirect work whenever new evidence changes the best path to the
mission outcome.

### Workers surface; managers decide

Workers should not silently expand their assignments or create their own swarm.
They should surface evidence and its possible significance. The manager remains
responsible for deciding whether it changes the plan.

### Waiting is not working

An agent should be active while it is investigating, deciding, changing, or
verifying something. Waiting for an external system should be durable state,
not a live agent session.

### Important does not mean automatically actionable

An important finding should promptly attract manager attention, but it should
not automatically create work. The manager must consider mission relevance,
evidence quality, overlap, cost, risk, and current priorities.

### Canonical state remains authoritative

Discoveries, waits, wakeups, and manager decisions must survive process exits
and restarts. Private agent messages or transient model context are not an
acceptable source of truth.

## Proposed product experience

### 1. The swarm responds as work finishes

The manager should be able to reconsider the plan whenever a task reaches a
meaningful outcome, even if unrelated agents are still running.

When capacity becomes available, newly justified work should be able to start
without waiting for every previously launched task to finish. Existing limits
on parallel work must still be respected.

The manager should see all relevant changes together and avoid reacting to
every low-value progress update. Routine checkpoints should not cause constant
replanning.

### 2. Agents can elevate new findings

An agent should have an explicit way to record a finding that may affect the
plan. A finding should communicate:

- what was discovered;
- the evidence supporting it;
- why it may matter to the mission;
- how significant the agent believes it is;
- a bounded recommended follow-up, if any.

Findings should support three levels:

- **Routine:** useful context for the manager's next normal review.
- **Material:** could change tasks, priorities, or workstreams and should prompt
  timely manager review.
- **Urgent:** may represent immediate safety, data-loss, security, or mission
  risk and should be prominently surfaced.

The manager must give every material or urgent finding an explicit disposition:

- **Incorporated:** the plan now accounts for it.
- **Deferred:** it matters, but the swarm will not pursue it now.
- **Dismissed:** the evidence does not justify follow-up or it is outside the
  mission.

The disposition should include a short rationale and, when applicable, links to
the resulting task or workstream.

Raising a finding does not authorize a worker to leave its assigned scope. If a
finding means current activity is unsafe, the worker must also use the existing
safety or blocking path rather than assuming that manager review will stop
another running process.

### 3. Tasks can wait for external conditions

A worker that starts or observes a long-running external operation should be
able to record:

- what condition it is waiting for;
- the external job or correlation reference;
- when the swarm should check again, or that an external signal is expected;
- a deadline after which the wait needs attention.

The worker should then exit. The task remains visibly waiting but consumes no
agent capacity.

The task becomes eligible for another short agent invocation when:

- its scheduled check time arrives;
- an external integration or operator signals that the condition changed; or

- its deadline arrives.

A wakeup means "check the real state now." It does not mean the external job
succeeded. A worker must inspect and verify the external system before
completing the task.

If the external operation is still running, the worker may record another
bounded wait. This produces a sequence of short checks rather than one
multi-hour agent session.

### 4. Active long-running work remains compatible

Some work genuinely requires a long-lived process rather than external waiting.
Swarmkit should allow that agent to remain active while the manager reacts to
other completed work and while free capacity is assigned elsewhere.

A long-running task continues to count against the parallelism limit. Swarmkit
must not imply that changing canonical state forcefully stops an already
running harness process or external side effect.

### 5. Waiting and findings are visible

The mission view should distinguish:

- actively running work;
- work ready to run;
- work waiting for an external condition;
- human decisions;
- new findings awaiting manager disposition.

For waiting work, the user should be able to see the condition, external
reference, next check, deadline, and how long it has been waiting.

For findings, the user should be able to see significance, source task,
evidence, recommendation, age, and manager disposition.

Urgent findings and overdue waits should appear in the existing "Needs
attention" experience.

### 6. Bounded runs remain bounded

Swarmkit should not require an always-on service. If a bounded run reaches a
point where all remaining work is waiting for future external conditions, it
should exit cleanly and report:

- that the mission is waiting externally;
- the earliest scheduled check, if one exists;
- whether any waits require an external signal;
- any approaching or missed deadlines.

An external scheduler can resume Swarmkit at the next check time. An
organization-owned integration can record an external wake and start another
bounded run.

## Example end-to-end experience

The mission is to determine why a delivery pipeline is unreliable and restore
correct operation.

1. The manager creates one task to inspect code behavior and another to run a
   representative pipeline job.
2. The code task finishes after five minutes and reports that retries can create
   duplicate records.
3. The finding is marked material. The manager reviews it while the pipeline job
   remains active and creates a bounded investigation of replay safety.
4. The pipeline worker receives a provider job ID, records that the job is still
   running, and leaves the task waiting for a check in fifteen minutes.
5. Its agent exits and the slot becomes available for the replay-safety task.
6. Fifteen minutes later, a short check finds the pipeline still running and
   schedules a later check.
7. A provider callback eventually wakes the task. A fresh worker verifies the
   actual pipeline result rather than trusting the callback alone.
8. The manager reconciles the pipeline result and replay-safety evidence,
   updates the workstreams, and selects the next justified intervention.

At every point, the board explains why the swarm is acting, waiting, or changing
direction.

## Functional requirements

### Responsive coordination

- A task finishing must be reviewable by the manager without waiting for other
  active tasks.
- Freed capacity must be reusable while unrelated tasks remain active.
- Material and urgent findings raised by an active agent must be reviewable
  before that agent necessarily exits.
- Manager reviews must be serialized and should combine nearby changes rather
  than thrash.
- Existing parallelism limits, task ownership, leases, dependencies, decisions,
  and policy constraints remain effective.

### Durable external waiting

- A task can enter a distinct external-waiting state.
- Entering the state releases its agent ownership and capacity.
- Every wait includes a condition and deadline.
- A wait can resume by scheduled check, explicit signal, or deadline.
- Repeated signals or simultaneous wake conditions must not create duplicate
  task execution.
- Waiting tasks do not satisfy dependencies and prevent premature workstream or
  mission completion.
- Wait history and wake reason remain auditable.

### Finding elevation and triage

- An active task owner can record a source-backed finding.
- Material and urgent findings prompt timely manager attention.
- Routine findings wait for the next normal manager review.
- Material and urgent findings require an explicit disposition before mission
  completion.
- Findings and resulting work remain linked in mission history.
- Workers cannot use a finding to authorize their own scope expansion.

### Recovery and safety

- Waiting and finding state survives restarts.
- If Swarmkit restarts after a wake, eligible work remains available.
- If an agent records a wait and then exits unexpectedly, the task remains
  waiting rather than being incorrectly requeued.
- A deadline wake is never presented as evidence that the external operation
  succeeded.
- Swarmkit does not claim that canonical cancellation terminated an external
  process unless the harness provides and confirms that capability.

## Non-goals for the first release

- A hosted webhook endpoint.
- Provider-specific pipeline, CI, deployment, or cloud integrations.
- Automatic pursuit of every interesting discovery.
- Automatic prioritization based solely on an agent's significance label.
- Force-cancelling arbitrary harness processes.
- An indefinitely running Swarmkit daemon.
- A general-purpose calendar or workflow scheduler.

## Product decisions

- The manager remains the sole planner. Workers surface findings but do not
  create follow-up tasks or workstreams.
- External waiting is separate from human blocking. A pipeline taking time is
  not a human decision and should not appear as one.
- Every external wait requires a deadline to prevent invisible indefinite
  waiting.
- Waking a task schedules verification; it never declares success.
- Responsive management should favor meaningful events over ordinary
  checkpoints.
- The default CLI remains suitable for cron or another external supervisor. It
  reports future wake needs instead of sleeping for hours.

## Success measures

### Responsiveness

- A completed short task can influence the plan while an unrelated long task is
  still running.
- A material finding is presented to the manager within a small, documented
  scheduling interval.
- Available task capacity is not left idle while ready work exists.

### Efficiency

- Tasks waiting on external systems consume no agent slot.
- Long external jobs are handled through short checks rather than continuous
  model sessions.
- Routine progress does not create excessive manager invocations.

### Reliability

- No wait is lost across process restart.
- No wakeup produces duplicate task ownership.
- No material or urgent finding disappears without a recorded disposition.
- Mission completion cannot hide unfinished waits or untriaged consequential
  findings.

### Clarity

- An operator can determine why the mission is waiting and what will resume it
  from the normal status views.
- An audit reviewer can trace a new workstream or follow-up task back to the
  finding that motivated it.

## Acceptance scenarios

1. **Mixed-duration work:** Two tasks begin together. One finishes quickly and
   causes the manager to create follow-up work, which starts before the second
   task ends.
2. **In-flight discovery:** A worker raises a material finding and continues its
   bounded task. The manager reviews the finding while that worker remains
   active.
3. **External polling:** A task checks an external job three times over several
   hours without retaining an agent between checks, then verifies and completes
   it.
4. **External signal:** A waiting task receives repeated completion signals but
   becomes eligible only once and still verifies actual provider state.
5. **Missed deadline:** A wait reaches its deadline and appears as needing
   attention without being reported as successful.
6. **Restart:** Swarmkit exits while tasks are waiting and later resumes with all
   wait conditions, findings, and history intact.
7. **Finding triage:** The manager incorporates one material finding, defers
   another, and dismisses a third; each disposition and rationale is visible in
   the audit trail.
8. **No churn:** Frequent routine checkpoints from active workers do not cause
   repeated manager invocations.

## Release expectations

The implementation owner should choose the internal state model and scheduling
mechanism that best fit the existing code. The release must include automated
coverage of the acceptance scenarios, migration of existing workspaces,
updated role guidance, updated operator and harness documentation, regenerated
CLI documentation, and a passing full release check.
