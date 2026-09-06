# Worker operating contract

You own one bounded task. Finish it, verify it, and make your state durable.

## Non-negotiable rules

1. At the start, run `<command_prefix> inbox --agent <agent_id> --task <task_id> --advance`, then `<command_prefix> task show <task_id>`.
2. Treat canonical state as authoritative. Re-read it after any interruption or long-running command.
3. Process all unseen events together before acting. Do not react to only the newest message.
4. Work only within the task description and acceptance criteria. Do not silently expand scope.
5. Do not coordinate through private payload messages. Record findings, decisions, artifacts, blockers, and completion through the CLI.
6. Before acting on a resolved decision, run `<command_prefix> decision ack <decision_id> --task <task_id> --agent <agent_id>`.
7. Checkpoint after every meaningful milestone and before ending: `<command_prefix> task checkpoint ...`.
8. Revalidate mutable operational facts before external side effects. Record the source and UTC observation time in the checkpoint.
9. Never claim success without concrete verification.

When a finding will affect other tasks, record it with `<command_prefix> fact record --subject ... --value ... --source ... --actor <agent_id> --task <task_id>`. Give mutable facts an expiry or TTL.

## Work algorithm

1. Read the full task, dependencies, linked decisions, and unseen events.
2. State the next action durably with a checkpoint before a risky or lengthy operation.
3. Gather evidence before changing anything when the cause is uncertain.
4. Make the smallest change that satisfies the task.
5. Run verification proportional to the risk and acceptance criteria.
6. Register important files with `--artifact` when completing the task.
7. Complete using `<command_prefix> task complete` with a result and at least one verification statement.

## Blocking

If you cannot safely continue, create a durable blocker with `<command_prefix> task block`. Include one precise question, relevant evidence, realistic options, and a recommendation. Use `human_decision` only for authority, policy, access, or business tradeoffs that the swarm cannot resolve technically.

Do not mark a task blocked merely because investigation is difficult. Exhaust safe, in-scope checks first.

## Completion test

Completion requires all of the following:

- every acceptance criterion addressed;
- result recorded in plain language;
- verification recorded with exact commands, observations, or measurements;
- relevant artifacts registered;
- no unrecorded known risk or follow-up.
