# Documentation policy

Documentation is part of Swarmkit's product contract. A behavior change is not
complete until the authoritative instructions, executable examples, tests, and
release metadata agree in the same commit.

## Document ownership

| Document | Authoritative for |
|---|---|
| `README.md` | Installation, quickstart, major capabilities, and release package name |
| `docs/USER_MANUAL.md` | Human-facing operational journeys |
| `docs/HARNESS_INTEGRATION.md` | Harness, skills, and extension integration contracts |
| `SETUP_AGENT.md` | Destination-machine discovery and acceptance tests |
| `docs/SYSTEM_EXPLAINER.md` | Architecture, invariants, and design rationale |
| `docs/POLICY_PACKS.md` | Policy-pack schema, lifecycle, and authoring contract |
| `docs/EXTENSIONS.md` | Delivery-extension manifest, outbox, adapter, and operations contract |
| `docs/CLI_REFERENCE.md` | Generated exact commands, arguments, choices, and defaults |
| `guidance/*.md` | Normative behavior for launched roles |
| `CHANGELOG.md` | User-visible changes, versions, and migrations |

Keep one normative home for each concept. Other documents should summarize and
link to it rather than maintaining competing copies.

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
alignment, public command presence, required extension coverage, and bundled
policy and delivery-extension manifests. `release_check.py` runs tests and documentation checks both in
the source tree and in a newly built, extracted distribution ZIP.

CI runs the same release check. Do not bypass it for documentation-only changes:
documentation examples and package contents are executable behavior.
