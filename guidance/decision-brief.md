# Decision reader contract

When requesting human authority, present the call first, then background for a
reader who has not followed the work, why human judgment is needed, realistic
options with consequences and risks, your recommendation, and the blocked outcome.
Put evidence and logs last under a separate heading. Keep decision-changing facts
in the brief even when their supporting details are long. Do not use length as a
substitute for clarity. State unknown risks rather than inventing certainty.

Use `task block --question 'Specific call?' --option EXACT_VALUE --brief FILE`.
The JSON contract is in docs/DECISION_BRIEFS.md. Option values are exact authority
identifiers; keep labels and explanations in option_details. New integrations
should enable `decision-contract --mode required`. Legacy missions still accept
old blockers. Supply a free-response form when there are no fixed options.

For continuing work, explain the actions authorized by each choice, the required
conditions, and the boundary for returning to the human. Permission to request
review alone is not merge permission. Reuse existing authority for ordinary fixes
it already covers; do not request the same permission again. External reviewer
approval, comment disposition, and CI status are separate facts.

Managers link every governed task. Liaisons present the canonical brief without
inventing background or hiding material consequences. All roles may retrieve the
complete record with `decision show`; shortened context is not the full request.
A new request or materially changed scope needs a new decision and explicit links;
never silently edit a resolved request or reuse its approval for changed terms.
