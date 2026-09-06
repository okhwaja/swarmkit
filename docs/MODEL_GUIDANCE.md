# Designing for smaller models

## How much instruction is enough?

Use enough instruction to remove ambiguity about protocol, ownership, and stopping conditions. Do not try to encode every possible technical situation.

A smaller model should receive five layers of context:

1. A short harness-wide contract that applies to every agent.
2. One role guide: manager, worker, briefer, verifier, liaison, status reporter, or delivery extension.
3. The current mission and exactly one assigned task when applicable.
4. All unseen durable events and current linked decisions.
5. Exact CLI commands for recording progress, blocking, and completion.

For a task linked to a persistent-service case, include the current case,
immutable payload references, all signals, and open decisions. Do not include
old provider transcripts unless they are recorded as case evidence.

The generated prompt assembles these layers. Avoid adding the full history of every agent conversation.

## Put reliability in code

If a behavior can be checked deterministically, enforce it outside the model.

| Failure | Mechanism |
|---|---|
| Agent forgets to update status | Completion and progress require CLI transitions |
| Two workers own the same task | Transactional claim and lease |
| Worker misses a human answer | Versioned decision plus acknowledgment gate |
| Agent acts on one new message | Durable cursor and batch inbox |
| Manager starts dependent work early | Dependency reconciler |
| Worker claims success vaguely | Required verification statements |
| Dead worker holds work forever | Expiring lease |
| Board becomes stale | Board is generated from SQLite |
| Email agent exits without sending | Delivery remains pending until a provider receipt is recorded |
| Retried delivery sends twice | Stable idempotency key plus provider-side deduplication |
| Webhook retry creates duplicate review | Unique case and signal source/external IDs |
| Long-lived reviewer develops context rot | Persistent case state with a fresh invocation per task or attempt |
| Author reply reaches only the old reviewer | Case signal plus task-scoped inbox events |
| Short work waits behind a long worker wave | Event-responsive scheduling fills each freed process slot |
| Consequential evidence stays inside a worker chat | Durable finding plus a serialized manager-review trigger |
| Provider polling consumes a model context for hours | `WAITING_EXTERNAL` releases ownership and wakes a fresh attempt |
| Duplicate callbacks launch duplicate work | Unique wait-signal source/external IDs and atomic wakeup |
| A deadline is mistaken for provider success | Deadline wake requires attention and explicit verification |

Prompting alone is a weak enforcement mechanism. A repeated failure should usually lead to a state-machine or validation change.

## Put specialized practice in a policy pack

Do not keep adding organization-specific workflows to every role prompt. Package
repeatable practice as a policy pack with explicit stages, dependencies,
acceptance criteria, and focused guidance. Swarmkit includes that guidance only
for the generated tasks that need it.

For a smaller manager, make `when_to_use` concrete and tell it to apply an
installed policy rather than manually recreating the stages. For workers and
verifiers, keep each policy stage narrow. A named harness skill is an observable
requirement: if it is unavailable, the agent records a blocker instead of
pretending that generic reasoning is equivalent.

Whenever a policy requires a fresh perspective, represent it as a separate task
and use `fresh_session_from` to prevent identity reuse. Do not ask one long-lived
conversation to forget its earlier conclusions.

Persistent logical agents should use the same rule at a larger scale. Persist
the service objective, constraints, reviewed policies, cases, decisions, and
sourced facts. Rotate the actual model context on every dispatch. A smaller
model is more reliable when it receives one current case than when it must
reconstruct authority from weeks of conversation.

The responsive loop follows the same principle inside one bounded run. A
manager review is a new, serialized invocation that receives all coalesced
triggers. A worker that discovers mission-changing evidence raises a finding;
it does not redesign the plan itself. A worker facing a long provider wait
records the condition, stable external reference, next check or expected
signal, and a mandatory deadline, then exits. The wake creates fresh work and
never counts as proof that the condition succeeded.

## Make every invocation mechanical

Smaller models benefit from an explicit loop:

```text
read inbox → read current record → reconcile changes → do one bounded unit
→ verify → write checkpoint or terminal state → stop
```

The role guides state this loop in direct language. Keep the steps stable across tasks so behavior becomes easy to evaluate.

## Use bounded fan-out

A weaker manager may interpret “parallelize” as “spawn as many agents as possible.” Give it numerical constraints:

- two to four discovery tasks at once;
- one task per worker;
- one owner for coupled implementation;
- no new task with substantial overlap;
- no implementation task until evidence supports an intervention;
- cancel speculative work invalidated by new findings.

The initial discovery questions should partition the uncertainty, such as timeline, data path, recent changes, and external-system health. They should not be several agents independently trying to solve the entire mission.

## Separate planning quality from worker quality

You may use a stronger model for the manager and verifier while using a cheaper model for narrow workers and briefers. If every role uses a smaller model, reduce the manager's choice space further:

- provide task templates for common mission types;
- require the manager to choose from a small set of discovery lenses;
- limit each manager cycle to one phase transition;
- use deterministic checks to reject overlapping or incomplete tasks;
- require a verifier before mission completion.

Do not assume a more expensive model is automatically required. Evaluate the complete system on representative ambiguous missions. Better state, tools, and constraints can matter more than a longer prompt.

For delivery agents, make the prompt even narrower than a worker prompt: one
immutable content file, one subject, an allowlisted recipient set, one provider
capability, and exactly two terminal updates (`delivery sent` or `delivery
fail`). Do not give an emailer the manager's planning context.

## Suggested evaluation cases

Run the harness repeatedly against controlled scenarios:

1. A pipeline fails because of an expired credential, with a misleading old log present.
2. A human resolves a decision while a worker is inactive.
3. Two findings arrive in the opposite order from when they were requested.
4. A worker dies after making a change but before reporting completion.
5. A proposed root cause is contradicted by a later trace.
6. A task reports success without checking the actual destination.
7. A short task completes while an unrelated long worker remains active.
8. Two callbacks race to wake the same external wait.
9. A provider never responds and the mandatory deadline passes.

Score whether the system restored the outcome, avoided unsafe actions, propagated decisions, canceled invalid work, and produced an audit trail that explains why each action happened.

## Signs that guidance is too long

- Agents quote policies instead of doing work.
- The current task is buried beneath general rules.
- The same instruction appears in several files with slightly different wording.
- Agents follow an old example more literally than current state.
- Prompt size grows with run duration even though old events are no longer relevant.

When this happens, move validation into code, shorten the role guide, and give agents a compact current snapshot plus an event cursor.

## Attempt-based escalation

Optional `runner.json` `escalation_models` selects a replacement role model for
subsequent task generations, while first attempts use `models`. Each run records
its selected model and task generation. This is deterministic attempt-based
routing, not an estimate of difficulty, safety, or cost. Confirmation/external
waits also produce fresh generations. See [runtime limits and evidence](RUNTIME_SAFETY.md)
and the [evaluation backlog](ROADMAP_BACKLOG.md) before choosing automatic policies.
