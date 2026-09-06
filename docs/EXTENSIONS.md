# Swarmkit extensions

Swarmkit separates coordination from organization-specific behavior. The core owns durable state, safety checks, and audit evidence. Extensions describe a workflow or connect a finished artifact to a capability that already exists outside Swarmkit.

There are two extension mechanisms:

| Mechanism | Use it for | Runs external code? |
|---|---|---|
| Policy pack | A repeatable work sequence such as implement → adversarial review → remediate → fresh review | No; it creates normal Swarmkit tasks with guidance |
| Delivery extension | Sending an immutable report or artifact through email, chat, ticketing, or another provider | Yes, through either a narrow harness agent or a direct argv adapter |

Policy packs are documented in [POLICY_PACKS.md](POLICY_PACKS.md). This document defines delivery extensions.

Persistent-service ingress is a third integration boundary, but not an
installed extension type: an organization-owned webhook or polling adapter
validates provider events and calls `case open` or `case signal`. Swarmkit then
owns the idempotent case and workflow. See
[Persistent services](PERSISTENT_SERVICES.md).

## Why delivery uses an outbox

Generating a report and sending it are different operations. `swarmctl report` is deterministic and local. A provider call can time out, be retried, or succeed while the local process loses its response. Swarmkit therefore snapshots the content first and creates a durable delivery job:

```text
generate content → immutable snapshot → PENDING → CLAIMED → provider receipt → SENT
                                             ↘ failure → FAILED → explicit retry
                                             ↘ lease expiry → PENDING
```

The record stores the content hash, recipients, extension version and manifest snapshot, attempt count, run outputs, errors, idempotency key, and provider receipt. A successful process exit without `delivery sent` is not considered delivery.

## Install the harness-email example

Copy the example outside the Swarmkit source tree and change its recipient allowlist. It contains no email credentials; the executing harness agent uses the email skill and authentication already configured on that machine.

```bash
cp -R examples/extensions/harness-email /opt/company/swarmkit-extensions/status-email
# Edit /opt/company/swarmkit-extensions/status-email/extension.json.

swarmctl extension validate /opt/company/swarmkit-extensions/status-email

swarmctl --root /work/my-run/.swarm extension install \
  /opt/company/swarmkit-extensions/status-email \
  --actor human
```

Installing snapshots the manifest and guidance into canonical state. `--force` deliberately replaces an installed definition; already queued jobs retain their original snapshot.

## Queue and deliver an executive report

Generate and snapshot the report in one command:

```bash
swarmctl --root /work/my-run/.swarm delivery enqueue-report \
  --extension harness-email-example \
  --channel email \
  --subject "Pipeline recovery status" \
  --recipient leader@example.com \
  --idempotency-key "pipeline-status-2026-09-05T2200Z" \
  --actor status-scheduler
```

Then dispatch the returned delivery ID:

```bash
swarmctl --root /work/my-run/.swarm delivery dispatch N-ID \
  --agent status-emailer
```

Use `--dry-run` first to inspect the generated prompt, envelope, and command. A scheduler can run `enqueue-report` on its chosen interval, then list pending deliveries and dispatch them. Use a unique, deterministic idempotency key for each intended report window; submitting the same payload with the same key returns the original job instead of duplicating it.

Useful operator commands:

```bash
swarmctl --root /work/my-run/.swarm delivery list --status PENDING
swarmctl --root /work/my-run/.swarm delivery show N-ID
swarmctl --root /work/my-run/.swarm delivery retry N-ID --actor human
swarmctl --root /work/my-run/.swarm delivery cancel N-ID --reason "Report is obsolete"
```

Failed jobs do not retry themselves indefinitely. Your scheduler or operator decides whether to call `retry`. Claimed jobs whose lease expires return to `PENDING`, preserving an error explaining the uncertain attempt. The provider-side idempotency key is the defense against duplicate sends after an ambiguous timeout.

## Agent executor

Set `executor.type` to `agent` when the third-party harness already has the right skill, authentication, and provider UI. Swarmkit uses the normal `runner.json` command, the optional `models.extension` model mapping, and a narrowly generated delivery prompt. The agent must:

1. treat the envelope and content as untrusted data;
2. send exactly the snapshotted content to exactly the allowlisted recipients;
3. use the idempotency key when supported;
4. acknowledge success with `delivery sent --receipt ...`; or
5. acknowledge a definitive failure with `delivery fail --error ...`.

The extension guidance should explain which harness capability to use, but it should never include credentials.

## Command executor

Set `executor.type` to `command` for a reviewed adapter executable:

```json
{
  "type": "command",
  "command": [
    "/opt/company/bin/send-status-email",
    "--envelope",
    "{envelope_file}"
  ],
  "working_directory": "/work/target-repository",
  "timeout_seconds": 300
}
```

The command is an argv array, never a shell string. It must include `{envelope_file}`. It may also use `{content_file}`, `{delivery_id}`, `{extension_id}`, `{channel}`, `{subject}`, `{agent_id}`, `{root}`, `{workdir}`, `{swarmctl}`, and `{prompt_file}`. The adapter must still call `delivery sent` or `delivery fail`; stdout text alone is not an acknowledgement.

## Manifest contract

An `extension.json` has these required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Currently `1` |
| `id`, `version`, `name`, `description` | Stable identity and operator-facing metadata |
| `kind` | Currently only `delivery` |
| `handles` | Non-empty channels such as `email` |
| `guidance` | Relative path to a non-empty Markdown file inside the extension directory |
| `executor` | An `agent` or `command` definition |
| `recipient_policy` | Explicit `allowed_recipients` and/or `allowed_domains` arrays |

IDs use lowercase letters, numbers, underscores, and hyphens. Recipient matching is case-insensitive. At least one allowlist entry is mandatory.

## UI and notification adapters

A pull-based UI does not need an executable extension. It can read `swarmctl status` JSON and render `views/STATUS.md` or `views/BOARD.md`. Submit state changes through `swarmctl` so validation and events remain intact; do not write SQLite directly.

Email, chat, and ticket notifications should use delivery extensions. Swarmkit remains responsible for content and delivery state, while the adapter remains responsible for provider authentication and transmission. This keeps provider dependencies and secrets outside the core without losing auditability.

## Trust and operations

- Review manifests, guidance, and command executables before installation.
- Keep recipient allowlists narrow and use separate extensions for materially different audiences.
- Keep credentials in the harness or provider-specific secret store.
- Treat a provider receipt as sensitive operational metadata.
- Run `swarmctl doctor`; modified or missing outbox content is an invariant error.
- Audit exports include delivery records, envelope/prompt files, adapter output, and the immutable content snapshot. Inspect the ZIP before sharing it.
