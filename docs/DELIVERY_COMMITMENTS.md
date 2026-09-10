# Delivery commitments

This is the U12 state, CLI, and harness contract. A commitment records responsibility
for a produced change until an agreed external outcome is observed. It is separate
from a task attempt, a registered file artifact, or the report-sending delivery outbox.
Provider credentials, action permissions, reviewer rules, and observation provenance
remain responsibilities of the trusted harness and provider adapter.

## Plan and hand off

A commitment has one producer task and one distinct nonterminal follow-up task,
a title, provider, environment, named terminal check, responsible manager scope,
schedule/deadline, version, and mission revision. At most one open commitment can
use a follow-up task. The provider reference and exact opaque revision are bound
by a currently leased producer/follow-up worker. Object replacement requires a new
commitment; authorized revision updates retain history and increment its version.

Use the bundled [author-to-merge pack](../examples/policy-packs/author-to-merge/GUIDANCE.md)
to publish authoring, human release, continuation, and the commitment atomically.
Installing the pack does not connect a provider or grant merge authority.
For individually planned tasks, use `task add --delivery-required` on the producer
and create its commitment before dispatch. Save this specification as JSON:

```json
{
  "producer_task": "T-PRODUCER",
  "followup_task": "T-CONTINUE",
  "title": "Land the agreed repair",
  "provider": "review-provider",
  "environment": "review-host",
  "terminal_check": "change-landed",
  "responsible": "mission-manager",
  "next_check_at": "2030-01-01T00:15:00Z",
  "deadline_at": "2030-01-02T00:00:00Z",
  "signal_expected": true
}
```

Use real future UTC times. At least a next check or an expected signal is required;
a deadline is mandatory. Unknown specification fields are rejected. Both tasks
must share their workstream/case scope and be quiescent at creation; do not add
delivery requirements to an active attempt. Link scopes before creating the record.

```sh
swarmctl commitment add --specification /work/commitment.json \
  --idempotency-key repair-delivery-1 --actor manager-ID
swarmctl commitment bind CM-ID --task T-PRODUCER --agent worker-ID \
  --expected-version 1 --external-ref change-123 --revision opaque-revision-1 \
  --idempotency-key uploaded-change-123
```

Creation also marks the producer as requiring a handoff. Completion refuses a
missing, unbound, unpublished, or obsolete commitment, or a terminal continuation.
Creating the producer with `--delivery-required` also catches a wholly omitted
commitment. Legacy tasks do not acquire this requirement from URLs or prose.

New commitments and adoptions created during manager review stay staged until
successful plan publication. They invalidate an earlier strict review commit.
Failed reviews leave them staged and visible for subsequent review. Already
published work continues under the normal claim gates.

## Observe, wait, and wake

The provider adapter performs an authenticated read and supplies this exact JSON
shape. Save it as a file and pass it to `commitment observe`:

```json
{
  "provider": "review-provider",
  "external_ref": "change-123",
  "revision": "opaque-revision-1",
  "environment": "review-host",
  "check": "change-landed",
  "observed_at": "2030-01-01T00:01:00Z",
  "outcome": "pending",
  "receipt": "Provider observation identifier and relevant read-back details"
}
```

`observed_at` must be actual current UTC time, no more than 300 seconds old and
not in the future. The named check and provider/object/revision/environment must
match the record exactly. Outcomes are `pending`, `rejected`, `unknown`, or `satisfied`. An `unknown`
record describes an unavailable/inconclusive provider check; its scope fields name
the attempted target and its receipt explains the failure. It permits a bounded
backoff wait after a signal without pretending to have observed success.
Only a current assigned follow-up worker can record observations, after decision
acknowledgements; success additionally requires effect reconciliation. Core stores the complete observation
and receipt in SQLite, together with attempt generation, acceptance revision,
mission revision, and an audit event. This is a trusted harness attestation; core
does not independently query the provider or authenticate a local JSON file.

```sh
swarmctl commitment observe CM-ID --task T-CONTINUE --agent worker-ID \
  --expected-version 2 --observation /work/provider-readback.json \
  --idempotency-key check-123
swarmctl commitment wait CM-ID --task T-CONTINUE --agent worker-ID \
  --expected-version 2 --next-check-at 2030-01-01T00:15:00Z \
  --deadline 2030-01-02T00:00:00Z --signal-expected --idempotency-key wait-123
```

Waiting uses the existing external-wait transition, retires the worker attempt,
and updates the commitment schedule/version atomically. Exit the harness afterward.
If the wait command's result is uncertain, retrieve state rather than retrying with
an obsolete owner. Identical creation/binding/observation/adoption keys are replayable
under their applicable authority; different payloads under a key fail. Keys do not
bypass current ownership checks. Fetch `commitment show` for the current version.

Ingress validates the provider event and records a stable signal:

```sh
swarmctl commitment signal CM-ID --source review-provider \
  --external-id provider-event-123 --external-ref change-123 \
  --note 'Review state changed' --actor trusted-ingress
```

Signals deduplicate by commitment and provider event identity. They wake verification,
never mark success or authorize work. Late signals for cancelled/satisfied records
remain history without reactivation. Signals arriving before publication are retained
for reconciliation afterward. If a signal arrives after the last observation and
before a new wait, the worker must inspect and record the newer state before waiting.

Reconciliation handles due checks, deadlines, and missing follow-up coverage,
requesting durable manager review. It wakes an existing task wait when applicable;
it does not invent or approve a replacement task. Each deadline/version produces
attention once, independently of an earlier scheduled check. An idle commitment
survives a terminal or cancelled follow-up and appears as a tracking gap.

`run` reports commitment schedules with external waits. Configure `serve` or a host
supervisor and webhook/polling ingress to resume bounded runs. Paused missions may
record signals but cannot dispatch work; records do not install a daemon or provider.

## Completion, cancellation, and recovery

`OPEN` is outstanding responsibility; `SATISFIED` requires a matching current
terminal observation after producer completion; `CANCELLED` is an explicit audited
disposition. Provider closure without landing is `rejected`, leaves responsibility
open, and requests replanning. Queue admission and green CI alone are `pending`.

Open commitments block finite mission completion and workstream completion. Cases
with all tasks terminal remain waiting when they have open commitments. Task
cancellation does not cancel the commitment. Workstream cancellation requires its
commitments to be explicitly disposed first. Case/mission cancellation disposes
open commitments with the same reason without erasing effects or stopping remote
operations. Cancelled commitments contribute to partial outcomes under the existing
completion rules. Successful completion still requires actual outcome evidence.

Use `commitment adopt --followup-task ... --expected-version ... --reason ...
--idempotency-key ... --actor ...` to assign replacement work or adopt a commitment
after mission amendment. Old and new follow-up tasks must be quiescent, with no
unfinished harness or uncertain effects. Adoption preserves the object/history,
updates mission revision, and does not approve new work. Explicitly cancel an
obsolete task when appropriate; adoption alone does not cancel it. New deadlines
are set by the subsequent current worker's bounded wait.

Use `commitment cancel CM-ID --expected-version ... --reason ... --actor ...` to
withdraw tracking deliberately. This does not revoke action grants, cancel its
tasks, undo an effect, or imply that an uncertain provider operation failed.
Use the relevant task/mission and grant controls when stopping execution too.

Status, task/case details, `why`, board/report, prompts, health checks, and private
exports expose commitments. Schema 14 upgrades are additive and transactional;
old databases begin with no inferred obligations. Back up state before upgrading.

Proposed-task external-condition gates remain deferred. The continuation can
already wait durably; ordinary dependency edges can sequence work after its verified
completion. Phase B's commitment survives independently if that task is replaced.
