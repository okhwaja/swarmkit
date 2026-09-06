# Workflow contract

Read current task, dependencies, decisions, and leased inbox deliveries. Acknowledge
only after applying each delivery. The harness and tools enforce actual permissions.
Use durable confirmation blockers and external waits instead of keeping a process
alive. Before changing another system, prepare and start an effect with a stable
idempotency key and exact target revision; record a provider receipt. Never replay
an uncertain action. Reconcile it first.

Parallel implementation stages need separate task workspaces. Only the integration
stage combines their changes. The verification stage starts with a fresh identity,
sets or uses the manager's exact revision/environment contract, and records evidence
for every criterion. A no-improvement finding or unsupported journey must be stated
explicitly; never claim success by omitting it. Budget exhaustion, pending approval,
or missing representative data are useful stopping points and require a clear handoff.
