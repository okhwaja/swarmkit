# Conditional grants

A grant records conditional authority for an exact external action scope. Swarmkit
checks durable scope and evidence; the harness authenticates actors, restricts which
commands they may invoke, runs trusted checks, and enforces provider permissions.
Actor strings alone are not an authentication mechanism.

## Issue a scoped grant

First resolve a decision with an explicit offered choice. The issuer then calls
`grant issue --decision ID --choice OPTION --actor ISSUER --specification JSON`.
The specification has these exact fields:

```json
{
  "provider": "review-service",
  "action": "submit",
  "resources": ["change-123"],
  "revision": "opaque-revision-7",
  "environment": "review-host",
  "delegate": "release-operator",
  "expires_at": "2099-01-01T00:00:00Z",
  "conditions": [{
    "id": "required-checks",
    "check": "provider-required-checks",
    "waivable": false,
    "max_age_seconds": 60
  }]
}
```

Use an appropriate short expiry for actual work; the distant timestamp above is
only a schema illustration. Resources are an explicit allowlist. Wildcard `*`
resources are rejected. Provider, action, revision, and environment match exactly;
revision strings are opaque and never interpreted as Git identifiers.

The grant binds the current decision version. Any answer revision invalidates it,
even if the selected option is preserved. Reissue a reviewed grant against the
new version rather than inheriting old authority. `grant revoke ID --actor ISSUER
--reason '...'` revokes it explicitly. Issuance and revocation are audit events.
`grant show ID` includes its specification, evaluations, and waivers.

Grant IDs distinguish immutable issued specifications. A new grant is a separate
reviewed authorization, not an in-place edit to old conditions. No production grant
is created automatically by installing or upgrading Swarmkit.

## Run and record trusted checks

A condition's `check` is a trusted harness-defined name, not shell text. The harness
maps it to a reviewed read-only check. Swarmkit never executes a command embedded
in a grant, decision, finding, or provider response.

The bundled `examples/check_condition.py` illustrates one narrow adapter: it reads
an already-obtained provider observation containing `revision`, `environment`,
`observed_at`, and `values`, compares one named field with an exact JSON value,
and exits zero only on a match. Missing/malformed data exits nonzero. The harness
is responsible for the observation's provenance and freshness; a local JSON file
is not independently authenticated provider evidence.

After running a trusted check, record its result:

```sh
swarmctl grant record GRANT --task TASK --agent CURRENT_AGENT \
  --condition required-checks --check provider-required-checks \
  --revision opaque-revision-7 --environment review-host \
  --exit-code 0 --path /work/results/check.json \
  --observed-at 2026-09-10T12:00:00Z --expires-at 2026-09-10T12:01:00Z
```

Use current timestamps, the actual exit code, and a durable result file. Recording
requires current task ownership and decision acknowledgments. Evaluations bind
that attempt generation, mission revision, acceptance revision, scope, observation
window, and file hash. The observation cannot come from the future and must still
be current. Its lifetime cannot exceed the condition's `max_age_seconds`.
Result files are registered artifacts for audit export. Evaluations remain
append-only; a later failed result supersedes an earlier passing result for that
condition. A missing, expired, mismatched, or tampered result does not pass.

## Explicit waivers

`grant waive ID --condition CONDITION --actor DELEGATE --reason '...'
--expires-at TIMESTAMP` records a waiver only if that condition is marked
waivable and the actor is its issuer or named delegate. Waivers need an explicit
reason and an expiry within the grant lifetime. Non-waivable conditions cannot
receive waivers. Revoking or revising the grant's decision invalidates its use,
including any associated waiver.

Every required condition must either pass now or have a valid explicit waiver.
Marking a condition waivable does not waive it. Timeouts, failed checks, and silence
never supply permission. The named delegate identifies who may waive a condition;
the harness separately controls which task worker may perform the scoped action.

## Bind the external effect

Use `grant require` for a diagnostic check of all scope fields and current results.
For execution, attach the grant to the existing effect ledger:

```sh
swarmctl effect prepare --task TASK --agent CURRENT_AGENT --key stable-action-key \
  --target change-123 --revision opaque-revision-7 --parameters '{}' \
  --grant GRANT --provider review-service --action submit --environment review-host
swarmctl effect start EFFECT --actor CURRENT_AGENT
```

`effect prepare` checks the grant and records its binding. `effect start` checks it
again in the same write transaction as the transition to EXECUTING, recording the
condition vector in an audit event. Ownership and expiry are rechecked after file
hashing, so a slow result read cannot outlive the worker lease. A retry cannot silently remove or change that
binding. The adapter must enforce the exact same provider/action/resource/revision
at the provider call and honor current tool authority. A local transaction cannot
make a later provider operation atomic or prevent remote state changing meanwhile.

Use the existing stable provider idempotency key and reconciliation contract.
If execution may have occurred but a receipt was lost, retain UNKNOWN and query
the provider. Revoking authority does not undo an already-started external action.
Do not blindly retry, infer non-application from process exit, or treat a successful
condition check as a delivery receipt.

These commands coordinate authority; they do not replace credential enforcement,
create automatic approval policy, or make an irreversible action reversible.
