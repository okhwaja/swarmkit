# Example: ambiguous pipeline incident

## Initial human request

> A critical data pipeline stopped delivering data to its destination. Determine what happened, restore correct delivery, safely handle any backlog, and prevent silent recurrence. Ask me only for decisions involving production risk, access, or business tradeoffs.

## Mission contract

```bash
bin/swarmctl --root /work/pipeline-incident/.swarm init \
  --objective "Restore correct and reliable data delivery through the critical pipeline" \
  --success "New source records arrive at the destination" \
  --success "Completeness and correctness are verified with representative records" \
  --success "The backlog is drained or explicitly accounted for without loss or duplication" \
  --success "Monitoring detects this failure mode" \
  --constraint "Require human approval for destructive production actions" \
  --constraint "Preserve customer data" \
  --constraint "Prefer reversible mitigation before permanent repair"
```

## A reasonable first manager wave

The manager might create these tasks after reading the mission:

1. Establish the last successful delivery, first failure, and current stage boundaries.
2. Trace one representative record through source, transport, processing, and destination.
3. Compare relevant code, configuration, credentials, and infrastructure changes around the failure window.
4. Measure queue and backlog state, retry behavior, and replay safety.

These are examples, not mandatory tasks. The manager should use current evidence and avoid duplicating existing investigation.

## Expected convergence

When evidence supports a cause, the manager should stop broad discovery, cancel obsolete proposals, choose one owner for the coupled repair, and separately schedule validation of live delivery and backlog correctness.
