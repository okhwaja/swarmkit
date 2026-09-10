# Swarmkit user manual

This guide is for the person directing a mission: you describe the outcome,
answer decisions, and check whether the work is delivering what you need.
Swarmkit coordinates the agents that investigate, plan, execute, and verify it.

A **mission** is your overall goal. A **workstream** is a major part of that goal,
such as restoring live delivery or recovering a backlog. A **decision** is a
question that needs your answer before affected work can continue.

| What brings you here? | Start here |
|---|---|
| I want to begin work | [Start a mission](#start-a-mission) |
| Something needs my decision | [Answer a decision](#answer-a-decision) |
| I want to know how it is going | [Check progress](#check-progress) |
| I want to understand why | [Ask for an explanation](#ask-for-an-explanation) |
| I want to change direction or stop | [Change direction or stop](#change-direction-or-stop) |
| I want to review the result | [Review and take away the result](#review-and-take-away-the-result) |

Swarmkit currently provides commands and readable reports. If you work through
an agent that can operate Swarmkit, you can give it the requests described here;
it must record directions and answers in the mission. A chat reply on its own
does not update Swarmkit. Notifications depend on your configured integration.
The expandable examples below use the [installed CLI](../README.md#install-the-cli).
An agent can learn the workflow with `swarmctl guide`; use `swarmctl help ask`
(or any other command) for exact syntax and next steps.

## Start a mission

Give the swarm three things:

- **Outcome:** what should be different when the work is done?
- **Success criteria:** what evidence would convince you it worked?
- **Boundaries:** what must be preserved, avoided, or brought back for your decision?

For example:

> Restore reliable delivery through the customer data pipeline. Show that new
> records arrive and the backlog is accounted for without loss or duplication.
> Preserve customer data, and ask me before making production changes.

You can start with an uncertain diagnosis. The swarm can investigate and form a
plan; you do not need to design the tasks or assign individual agents.

Before real work can run, Swarmkit needs a connection to your agent harness—the
software that runs your agents and supplies their tools. Give whoever configures
it the [setup assignment](../SETUP_AGENT.md). They should return the setup report
and acceptance results. Your project can use jj, Git, or an internal checkout tool.

**What happens next:** the manager investigates the goal, organizes workstreams,
and dispatches work. Check the report for the plan and any questions it raises.

<details>
<summary>Terminal: create and run a mission</summary>

Run these commands from any directory. Replace the example state directory with
your own; reuse that directory for every command for this mission.

```sh
export SWARM_ROOT=/work/pipeline/.swarm
swarmctl init \
  --objective "Restore reliable pipeline delivery" \
  --success "New records reach the destination" \
  --success "The backlog is accounted for without loss or duplication" \
  --constraint "Preserve customer data" \
  --constraint "Ask before production changes"
```

Have your setup agent configure this mission's `runner.json` and verify the
integration, then start work:

```sh
swarmctl run --max-cycles 20
swarmctl status --brief
```

The run is bounded. It can stop at its cycle limit or while waiting for something;
that does not mean the mission is complete. Run it again when work is ready.
For unattended operation, have your setup agent configure the
[persistent controller](RUNTIME_SAFETY.md#planning-amendments-limits-and-services).

</details>

## Answer a decision

Open the decision named in the report or notification. Read the question,
affected work, available options, and recommendation. Before answering, make sure
you understand why the decision is needed and the consequences of your choice.
If that context is missing, [ask for an explanation](#ask-for-an-explanation).

Give a direct answer with any conditions. For example: “Allow the repair during
the maintenance window, for at most ten minutes.” If the decision offers explicit
choices, select the matching choice as well as explaining your answer.

**What happens next:** your answer is saved with the mission and reaches the
work it affects. Unrelated work can continue. A refusal must be honored; answering
a question does not automatically authorize the proposed action.

If execution stopped waiting for you, start it again. If you separately paused
the mission, it also needs to be resumed. To correct an earlier answer, revise
the original decision so the change is recorded and affected work receives it.

<details>
<summary>Terminal: inspect, answer, or revise a decision</summary>

These and later examples assume `SWARM_ROOT` is set as above. Copy the actual
returned decision ID in place of `D-ID`.

```sh
swarmctl decision list
swarmctl decision show D-ID
swarmctl decision resolve D-ID \
  --answer "Allow the repair during the maintenance window, for at most ten minutes"
```

When options are offered, add `--choice` with the exact option from the decision.
For example, if `withhold` is an offered option:

```sh
swarmctl decision resolve D-ID --choice withhold \
  --answer "Withhold approval until the retry path has a concurrency test"
```

Use one answer for the relevant decision. To change a saved answer, use
`decision revise D-ID --answer "Your corrected answer"`, including `--choice`
again when selecting an option. If the controller has stopped, continue with
`swarmctl run --max-cycles 20` after resolving any pause or recovery need.

</details>

## Check progress

Ask for the mission report. It gives you the major workstreams, their intended
outcomes, progress, forecast confidence, and needs from you. A workstream such as
“recover the backlog” stays understandable even as its individual tasks change.

Read the report with three questions in mind: **What has been achieved? What is
blocked? Does anything need me?** An unknown forecast is reasonable while the
swarm is still discovering the problem; a date should have a stated basis.

| What you see | What to do |
|---|---|
| Work is active or being verified | Check its progress and evidence; no intervention is usually needed. |
| A human decision is open | Open it and answer using the decision journey above. |
| Work is waiting on an external job | Check the waiting condition, next check, and deadline. Agents need not stay occupied during the wait; a controller must run to handle subsequent checks. |
| Work is blocked without a clear explanation | Ask why it is blocked and what would unblock it. |
| Execution stopped or recovery is required | Follow the reported next action. Have the person operating the harness inspect uncertain external actions before restarting them. |
| Work is marked done | Review the recorded outcome and evidence; some completed work can have a partial result. |

For a standing service, such as an ongoing change reviewer, the report groups
incoming requests into cases. An idle service may simply be waiting for its next
request. Its setup and intake procedures are in [Persistent services](PERSISTENT_SERVICES.md).

<details>
<summary>Terminal: open the progress report</summary>

```sh
swarmctl status --brief
swarmctl report
```

The first command gives a short update and next action. The second prints the
path to `views/STATUS.md`; open that file. Generate it again for a fresh report.
For more detail, `workstream list` and `workstream show WS-ID` inspect one area,
while `board` generates `views/BOARD.md` with individual tasks. `why` explains
current blockers and recovery needs without launching an investigation.

</details>

## Ask for an explanation

Ask a specific question: “Why did the forecast change?”, “What evidence supports
the diagnosis?”, or “What would unblock backlog recovery?” You can name a
workstream to narrow the investigation.

**What happens next:** a briefing task examines the recorded work and produces
an answer with evidence references and uncertainty. It takes an agent run, so the
answer is not immediate. Other work can continue while it is prepared.
An explanation request does not change priorities or grant permission.

<details>
<summary>Terminal: request and read an explanation</summary>

```sh
swarmctl ask \
  --question "Why does backlog replay need deduplication, and what evidence supports that?"
```

Optionally add `--workstream WS-ID`. Save the returned inquiry task ID. If no
controller is running, run `swarmctl run --max-cycles 5`, then inspect
`swarmctl task show T-INQUIRY-ID`. Once complete, its result and artifact
paths lead to the answer. If still pending, check progress before running again.

A paused mission needs to resume before the briefing can run. A completed or
cancelled mission cannot accept new briefing tasks; use its report and exported
evidence for a separate review.

</details>

## Change direction or stop

For a new objective or boundary, pause the mission and state the complete revised
goal, success criteria, and constraints. Record why they changed. After outstanding
activity is settled, amend the mission and resume it. The manager must reconsider
unfinished work against the new direction; completed history remains available.

Choose the stop behavior that matches your intent:

| Your intent | Action and effect |
|---|---|
| Let current work finish, then pause | **Drain** stops new work and pauses after active work finishes. |
| Pause coordination now | **Pause** stops new work and prevents active attempts from recording further task progress. |
| Continue a paused mission | **Resume** allows work again once outstanding activity and uncertain actions are resolved. |
| End the mission permanently | **Cancel** cancels remaining work and preserves its history. It cannot be resumed. |

Pause and cancel do not kill running processes or undo actions already sent to
external systems. If you need an external operation stopped, the person operating
the harness must handle that through its tools. See [runtime recovery](RUNTIME_SAFETY.md#stop-restart-and-change-direction)
if Swarmkit reports unfinished or uncertain activity.

<details>
<summary>Terminal: pause, amend, and continue</summary>

```sh
swarmctl pause --reason "Restrict this mission to diagnosis"
swarmctl recover
swarmctl why
```

Wait for running activity and resolve any reported uncertainty before amending.
Supply the **entire replacement** set of success criteria and constraints;
omitted ones are not carried forward.

```sh
swarmctl amend \
  --objective "Diagnose the pipeline failure and propose a repair" \
  --success "The diagnosis cites evidence and the repair proposal includes validation" \
  --constraint "Do not make production changes" \
  --constraint "Preserve customer data" \
  --reason "The production team will carry out the repair"
swarmctl resume --reason "Proceed with diagnosis only"
swarmctl run --max-cycles 20
```

For a graceful pause, use `drain --reason "Pause after current work finishes"`.
To end permanently, use `cancel --reason "This mission is no longer needed"`.

</details>

## Review and take away the result

Read the final report against the success criteria you set. Look for what was
delivered, the evidence supporting it, anything left incomplete, and remaining
risks or follow-up work. A `PARTIAL` outcome means you should inspect what was
left out; a stopped controller alone is not evidence of success.

The report is the starting point for a human review. Export the mission when you
want a fuller record for another reviewer, an analysis agent, or later reference.
The archive includes review instructions, recorded decisions, outputs, and optional
artifacts. It may contain confidential prompts and data, so inspect it before sharing.

<details>
<summary>Terminal: export the record</summary>

```sh
swarmctl report
swarmctl export \
  --output /work/exports/pipeline-run.zip \
  --include-artifacts
```

Choose an output outside the mission state directory. Start with `REVIEW_ME.md`
in the ZIP and check its omission reports for unavailable files. Export creates
a local archive; it does not send or publish it.

</details>

## For the person configuring or operating Swarmkit

The journeys above assume a working integration. Technical instructions have
separate homes:

- [Setup assignment](../SETUP_AGENT.md) and [harness integration](HARNESS_INTEGRATION.md): connect and verify your agent tools.
- [Runtime safety](RUNTIME_SAFETY.md): recovery, checkouts, evidence, limits, and lifecycle details.
- [Responsive orchestration](RESPONSIVE_ORCHESTRATION.md): agent findings and external waits.
- [Policy packs](POLICY_PACKS.md), [persistent services](PERSISTENT_SERVICES.md), and [extensions](EXTENSIONS.md): workflows, incoming requests, and report delivery.
- [CLI reference](CLI_REFERENCE.md): every command and its exact arguments.

## Correct a decision or acceptance requirement

Clarifying an answer preserves the option you already selected. Your agent can
replace that option explicitly or clear it when you withdraw structured consent.
Affected work still receives the new answer version before continuing.

When a task needs an additional acceptance check, ask for an acceptance amendment.
The agent first makes the task quiescent, records the complete revised criteria,
and obtains approval for that revised work. Its task identity and history remain;
evidence for the old contract does not prove the new one. Policy-owned work uses
its explicit policy replacement workflow.

The board and report place open decisions in “Needs attention,” with their ages
and affected work. To receive messages when attention is needed, configure an
explicit notification route with an installed delivery extension. No destination
is selected automatically. If manager retries stop, inspect the recorded failure,
repair it, and explicitly reset the review. A stopped service may need another
scheduled wake; polling exhaustion is visible in its result.

## Carry a change through review and merge

Ask for the whole outcome: “After I release this change for review, address every
comment, fix ordinary CI failures and conflicts, and merge when approved and ready.”
Your release decision should explain that continuing permission and its limits.
Ordinary covered repairs should not require you to repeat the instruction.

The report distinguishes authoring completion from an open delivery commitment.
It shows who is responsible, the follow-up task, next check, and deadline. A
tracking gap means follow-up needs reassignment; it does not mean the change landed.
The configured harness handles provider review, repairs, and merge, while Swarmkit
preserves responsibility during idle time and restarts. See
[delivery commitments](DELIVERY_COMMITMENTS.md) for optional CLI details and
[decision briefs](DECISION_BRIEFS.md) for the question format.
