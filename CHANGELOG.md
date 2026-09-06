# Changelog

## 0.4.0

- Added reviewed delivery extensions with agent and direct-command executors.
- Added a durable, hashed outbox with recipient allowlists, idempotency keys,
  leases, explicit provider acknowledgements, failures, and retries.
- Added `delivery enqueue-report` so schedulers can generate executive status
  content separately from provider transmission.
- Added extension and delivery state to boards, status reports, health checks,
  and audit exports.
- Added the harness-email example and operator, setup, integration, and
  extension-authoring documentation.
- Extended the release gate to validate delivery-extension docs, manifests,
  lifecycle tests, and extracted package behavior.

## 0.3.0

- Added declarative policy packs for organization- and project-specific agent
  workflows without hard-coding those workflows into Swarmkit.
- Added durable policy applications that expand a policy into an auditable task
  dependency graph.
- Added fresh-agent constraints between policy stages.
- Added the `pr-adversarial-review` example policy with two separate adversarial
  reviews and remediation gates.
- Added a generated CLI reference plus source and extracted-package
  documentation/release checks.

## 0.2.1

- Added the destination-machine setup-agent playbook and `setup-check` command.

## 0.2.0

- Added first-class executive workstreams, forecasts, briefings, and status
  reporting.
