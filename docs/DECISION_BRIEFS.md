# Decision briefs

This is the interface contract for U11 structured decisions. The shared
[role reader contract](../guidance/decision-brief.md) defines authoring and
presentation responsibilities and is included in worker, manager, and liaison prompts.

A brief gives an unfamiliar reader enough context to decide before opening the
logs. The question names the call; background, human authority boundary, option
consequences/risks, recommendation, and blocked outcome follow. Evidence is last.
Important uncertainties stay in the brief, with supporting details in evidence.
A structured record checks completeness, not the truth or clarity of its contents.

## Enable and create

Existing missions and newly initialized generic missions default to `legacy` for
API compatibility. Configure new unattended integrations explicitly:

```sh
swarmctl decision-contract --mode required --actor human
swarmctl decision-contract
```

Required mode rejects new `human_decision`, `missing_access`, and `safety_stop`
blockers without a brief. Other blocker kinds may carry a brief but do not require
one. Existing legacy decisions remain readable and actionable in either mode;
no background or authorization is inferred from their historical text.

Save this JSON as a file, adapting its facts to the actual decision:

```json
{
  "schema_version": 1,
  "background": "The search repair is uploaded and tested. External review has not started.",
  "human_reason": "You control release for review and authority to merge.",
  "option_details": [
    {
      "value": "CONTINUE",
      "label": "Review through conditional merge",
      "consequence": "Request review, address every comment, repair ordinary CI/conflict failures, and merge when valid review approval and all required checks hold.",
      "risk": "Review may require more work; changes outside the agreed scope return to you."
    },
    {
      "value": "DEFER",
      "label": "Keep the change pending",
      "consequence": "Do not request review or merge. The manager records the next disposition.",
      "risk": "The fix remains undelivered."
    }
  ],
  "recommended_option": "CONTINUE",
  "recommendation_rationale": "The scoped continuation has explicit checks and a human escalation boundary.",
  "blocked_outcome": "External review and landing of the search repair.",
  "response_required": null,
  "evidence": [
    {"reference": "test-report", "summary": "Exact revision, commands, results, and observation time."}
  ]
}
```

```sh
swarmctl task block T-ID --agent worker-ID --kind human_decision \
  --question 'May we release this repair through review and conditional merge?' \
  --option CONTINUE --option DEFER --brief /work/decision-brief.json
```

The current owner creates the blocker and brief in one transaction with audit
events, then its attempt ends. `question` stays separate from the brief. Every
shown field is required; unknown fields are rejected. Option details must match
all offered values exactly once. Labels, consequences, and risks are nonempty.
Recommendation is an exact offered value or null, always with a rationale.
Evidence is a list of reference/summary pairs; it may be empty when no supporting
reference exists. Include measurement times in summaries where relevant.

For a free-response decision use no `--option`, an empty `option_details`, null
`recommended_option`, and a nonempty `response_required` describing the needed
answer. Free response cannot authorize an exact-option action through
`decision require-choice`.

## Read, answer, and change scope

`decision show/list` returns `brief` alongside the existing fields. Board and
operator report use one shared renderer, including options and consequences.
Task prompts include linked briefs; bounded context points to full retrieval.
The legacy `recommendation` field is derived from the structured recommendation
when a brief is supplied, preventing contradictory recommendations in different
views. Exact option strings and the existing `selected_option` protocol are unchanged.

Resolve with the human's actual answer and exact offered choice. Link every task
that must obey it. Workers acknowledge the current version before action. Permission
to request review alone is not permission to merge; an explicitly authorized
continuation should not require repeated consent for ordinary covered repairs.
External reviewer approval and technical readiness are separate conditions.

Request briefs are immutable. To change a call, its options, or material terms,
create a new gate task/decision and explicitly link governed work to it; an open
linked decision fences that work. Do not carry an earlier choice to changed terms.
`decision revise` continues to revise the *answer* with existing version fencing,
choice preservation/clearing, and grant invalidation semantics. Neither prose nor
an actor string replaces the harness's authentication and tool permissions.

Schema 14 adds a companion table, retaining original decisions and audit history.
