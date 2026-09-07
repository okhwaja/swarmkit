# Policy packs

Policy packs extend Swarmkit with organization- or project-specific ways of
working. They live outside the Swarmkit core and contain declarative workflow
stages plus guidance. Swarmkit validates, snapshots, schedules, and audits them;
the third-party harness supplies any named skills and external credentials.

Use a policy pack when a best practice is a repeatable sequence with observable
gates. For example, “use good judgment when reviewing code” is merely advice,
while “open a PR, run adversarial review, remediate, run a fresh adversarial
review, then leave all checks green” is a workflow Swarmkit can enforce.

## Operator journey

Keep private policy packs in an organization-owned repository or managed local
directory, separate from Swarmkit. Validate one without a mission:

```bash
swarmctl policy validate /opt/company/swarmkit-policies/pr-adversarial-review
```

Install it into a mission. Installation snapshots the manifest and guidance in
canonical state:

```bash
swarmctl --root /work/my-run/.swarm policy install \
  /opt/company/swarmkit-policies/pr-adversarial-review \
  --actor human
```

List or inspect installed packs:

```bash
swarmctl --root /work/my-run/.swarm policy list
swarmctl --root /work/my-run/.swarm policy show pr-adversarial-review
```

Apply a pack to create its task graph atomically:

```bash
swarmctl --root /work/my-run/.swarm policy apply \
  pr-adversarial-review \
  --workstream WS-ID \
  --var 'goal=prevent duplicate replay records' \
  --var 'base_branch=main' \
  --var 'test_command=python3 -m unittest' \
  --actor manager \
  --idempotency-key review-request-123 \
  --ready
```

`--ready` authorizes every generated stage, but dependencies expose only the
first stage as ready. Without it, the stages remain proposed until authorized.

Use a stable `--idempotency-key` when a manager or ingress adapter may retry a
workflow request. An identical retry returns the original application and tasks,
even after a pause or completion. Changing the installed manifest/guidance,
resolved variables, workstream, or authorization under that key is rejected.
Actor identity and variable ordering do not change the request. Without a key,
each application deliberately creates a new plan. Keys and the full task graph
commit together; a failed application does not consume its key.

Inspect all applications or one application:

```bash
swarmctl --root /work/my-run/.swarm policy applications
swarmctl --root /work/my-run/.swarm policy application P-ID
```

The board also shows policy-application progress.

## PR adversarial-review example

The bundled example is
`examples/policy-packs/pr-adversarial-review/`. It creates this durable sequence:

```text
implement and open PR
  → adversarial-review task in a different agent invocation
  → remediate findings and restore green checks
  → adversarial-review task with a fresh agent identity
  → resolve remaining findings and leave the PR green
```

Both reviews are verification tasks, so the runner launches the verifier role.
Their task context includes the pack's `GUIDANCE.md`, including the requirement
to invoke the harness skill named `adversarial-review`. If that skill is not
installed, the verifier must record a blocker rather than substituting a normal
self-review.

The first reviewer cannot reuse the implementer's agent identity. The second
reviewer cannot reuse either the first reviewer's or remediator's identity.
Swarmkit enforces those constraints when tasks are claimed. The harness setup
contract separately requires every dispatch to create a fresh model context;
both properties are needed for a genuine fresh-session review.

Swarmkit does not create PRs or run the review skill itself. Those capabilities,
authentication, permissions, and provider-specific behavior remain in the
harness.

## Pack structure

```text
my-policy/
  policy.json
  GUIDANCE.md
```

Minimum manifest shape:

```json
{
  "schema_version": 1,
  "id": "my-policy",
  "version": "1.0.0",
  "name": "Human-readable name",
  "description": "What the workflow guarantees",
  "when_to_use": "How a manager recognizes applicable work",
  "guidance": "GUIDANCE.md",
  "variables": {
    "goal": {
      "description": "Bounded desired change",
      "required": true
    }
  },
  "stages": [
    {
      "id": "implement",
      "title": "Implement {goal}",
      "description": "Make the bounded change.",
      "kind": "implementation",
      "priority": 70,
      "acceptance": ["The requested outcome is verified"]
    },
    {
      "id": "review",
      "title": "Review {goal}",
      "description": "Independently review the completed change.",
      "kind": "verification",
      "depends_on": ["implement"],
      "fresh_session_from": ["implement"],
      "acceptance": ["Review evidence is recorded"],
      "completion": {
        "minimum_artifacts": 1,
        "artifact_files_required": true,
        "verification_terms": ["reviewed commit SHA"]
      }
    }
  ]
}
```

Stages must be topologically ordered: `depends_on` and `fresh_session_from` may
name only earlier stages. Supported task kinds are `discovery`, `implementation`,
`verification`, and `briefing`. Titles, descriptions, and acceptance criteria may
reference declared variables with `{name}` placeholders.

Optional `completion` rules add deterministic gates beyond acceptance prose:

- `minimum_artifacts` rejects completion without enough registered artifacts;
- `artifact_files_required` rejects missing or purely notional artifact paths;
- `verification_terms` requires named evidence concepts in the recorded
  verification statements.

These checks make omissions visible, but they do not prove that a model told the
truth about invoking a skill. Provider-native skill receipts can later be
registered as artifacts when the harness exposes them.

## Trust and lifecycle

A policy pack is operator-supplied instruction and should be reviewed before
installation. Pack guidance is inserted into agent task context, so do not
install a pack sourced from an untrusted pull request or external message.
Conversely, repository content, PR comments, logs, and artifacts remain
untrusted data even when a policy tells an agent to inspect them.

Manifests must not contain credentials. Skills and authentication stay in the
harness. Policies do not execute code during installation or application; they
only create task records and prompt guidance.

Replacing an installed pack requires `policy install --force`. Existing policy
applications retain their original version, manifest, and guidance snapshot.
New applications use the replacement version. Use semantic versions and record
meaningful changes in the policy pack's own repository.

Policy-generated tasks obey ordinary Swarmkit leases, decisions, checkpoints,
artifacts, cancellation, and audit export rules. A policy does not bypass mission
constraints or grant authority for external side effects.

A policy stage may also raise a durable finding or enter `WAITING_EXTERNAL`.
The stage remains the same task: a wake starts a fresh attempt that must verify
the external condition before completion, and downstream stages remain blocked.
A finding does not let the stage create or skip policy work; the manager alone
dispositions it and changes the plan. See
[Responsive orchestration](RESPONSIVE_ORCHESTRATION.md).

## Policies for persistent-service cases

`case open --policy ...` applies a reviewed pack to one idempotent inbound case
and links every generated stage to its dedicated workstream. Later signals and
decision versions therefore reach the correct fresh task owner.

The bundled `human-gated-change-review` example demonstrates cold analysis, a
digestible explainer, a versioned human gate, an external-response wait, and a
fresh final disposition check. It is intentionally provider-neutral. Copy and
adapt it outside Swarmkit before production use; provider comments, approvals,
skills, and credentials remain harness responsibilities. See
[Persistent services](PERSISTENT_SERVICES.md).

## Runtime safety and recovery (0.7.0)

The [durable runtime contract](RUNTIME_SAFETY.md) documents `pause`, `drain`,
`resume`, `cancel`, `abandon`, `recover`, `why`, and `serve`, along with leased
inboxes, effect reconciliation, task worktrees, resource leases, evidence
contracts, amendments, limits, model escalation, and audit verification.
Use its examples for new integrations. The
[roadmap backlog](ROADMAP_BACKLOG.md) distinguishes shipped slices from remaining
engineering work and owner decisions. Permission enforcement stays with the
harness and tools. Runtime process locking requires a single POSIX host.

Malformed stage kinds, dependency values, and template field expressions are
reported as policy validation errors. Templates must render from the declared
variables; validation does not invoke the harness or execute policy prose.
