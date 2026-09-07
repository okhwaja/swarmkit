# Documentation policy

Documentation is part of Swarmkit's product contract. A behavior change is not
complete until the authoritative instructions, executable examples, tests, and
release metadata agree in the same commit.

## Document ownership

| Document | Authoritative for |
|---|---|
| `README.md` | Installation, quickstart, major capabilities, and release package name |
| `docs/USER_MANUAL.md` | Mission-owner interaction: start, decide, follow progress, ask, redirect, and review |
| `docs/HARNESS_INTEGRATION.md` | Harness, skills, and extension integration contracts |
| `SETUP_AGENT.md` | Destination-machine discovery and acceptance tests |
| `docs/SYSTEM_EXPLAINER.md` | Architecture, invariants, and design rationale |
| `docs/POLICY_PACKS.md` | Policy-pack schema, lifecycle, and authoring contract |
| `docs/EXTENSIONS.md` | Delivery-extension manifest, outbox, adapter, and operations contract |
| `docs/PERSISTENT_SERVICES.md` | Service missions, cases, signals, ingress, and fresh-context contract |
| `docs/RESPONSIVE_ORCHESTRATION.md` | Manager triggers, findings, external waits, wakeups, and responsive scheduling |
| `docs/RESPONSIVE_ORCHESTRATION_PRODUCT_SPEC.md` | Responsive-orchestration product intent and acceptance scenarios |
| `docs/RUNTIME_SAFETY.md` | Runtime recovery, lifecycle, effects, evidence, limits, and migration contract |
| `docs/CLI_REFERENCE.md` | Generated exact commands, arguments, choices, and defaults |
| `guidance/*.md` | Normative behavior for launched roles |
| `CHANGELOG.md` | User-visible changes, versions, and migrations |

Keep one normative home for each concept. Other documents should summarize and
link to it rather than maintaining competing copies.

The user manual serves the human directing the mission. Lead with the person's
question, what they should do, and what happens next. Keep terminal syntax optional
and subordinate to those journeys. Setup, worker/manager protocols, adapter
configuration, and detailed recovery belong in their technical homes above.
Document user-visible limitations where they affect the next action.

## Required change workflow

Every product task must classify its documentation impact as one or more of:

- CLI or state contract;
- user journey;
- harness or extension contract;
- setup procedure;
- architecture;
- role behavior;
- migration and release metadata;
- none, with a short rationale.

Before completion, update every affected authoritative file and run:

```bash
python3 scripts/generate_cli_docs.py
python3 scripts/check_docs.py
python3 scripts/release_check.py
```

The implementation owner reports the impacted documents and results. A fresh
reviewer should compare the complete code-and-documentation diff for semantic
gaps. Generated checks catch structural drift; the reviewer checks whether a new
operator could actually follow the instructions.

## Automated guarantees

`check_docs.py` verifies required documents, internal links, version/package
alignment, generated CLI help, role guidance, and bundled
policy and delivery-extension manifests. `release_check.py` runs tests and documentation checks both in
the source tree and in a newly built, extracted distribution ZIP.

CI runs the same release check. Do not bypass it for documentation-only changes:
documentation examples and package contents are executable behavior.

Distribution builds select only known source/documentation directories and explicit
root files. They exclude symlinks, runtime directories containing `state.sqlite3`,
hidden local files, and development caches. Documentation checks use that same
file selection, so private mission Markdown is not treated as product documentation.
Checks do not require arbitrary phrases in the README: executable examples and
generated command help carry the interface contract, while prose needs editorial
review for clarity and correctness.
