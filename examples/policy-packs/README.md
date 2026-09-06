# Example policy packs

These packs demonstrate Swarmkit's workflow-extension contract. They are not
installed automatically and are not universal Swarmkit behavior.

For production use, copy the relevant pack into an organization- or
project-owned policy repository, review it, adapt its stages and skill names to
your harness, give it its own version history, and install that reviewed path
into each applicable mission.

- `pr-adversarial-review`: open a PR, run adversarial review, remediate, run a
  fresh adversarial review, and leave the PR passing.

See [Policy packs](../../docs/POLICY_PACKS.md) for validation, installation,
application, trust, and authoring rules.

## Operational workflow templates

`performance-investigation`, `pipeline-repair`, and `system-port` use the same
policy graph and runtime primitives. Install a directory, then apply it with
`--var goal='concrete outcome' --var test_command='approved test command'`.
Performance and port templates include parallel stages and an explicit integration
owner followed by fresh verification. Set exact revision/environment evidence
contracts before claiming the generated tasks. These templates do not configure
provider credentials, approve risky actions, or install background services.
