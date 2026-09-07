# CLI reference

Generated from `swarmctl.py` for version `0.7.1`. Do not edit by hand; run `python3 scripts/generate_cli_docs.py`.

## `swarmctl`

```text
usage: swarmctl [-h] [--root ROOT] [--version]
                {pause,drain,resume,cancel,abandon,recover,why,configure,amend,effect,resource,evidence,review-commit,workspace,serve,audit-verify,init,demo,status,board,report,reconcile,doctor,setup-check,ask,policy,case,extension,delivery,workstream,task,decision,finding,wait,fact,inbox,prompt,dispatch,run,mission,export}
                ...

Argument parsing and command routing. Domain rules live in the owning modules.

positional arguments:
  {pause,drain,resume,cancel,abandon,recover,why,configure,amend,effect,resource,evidence,review-commit,workspace,serve,audit-verify,init,demo,status,board,report,reconcile,doctor,setup-check,ask,policy,case,extension,delivery,workstream,task,decision,finding,wait,fact,inbox,prompt,dispatch,run,mission,export}
    pause               Set durable mission lifecycle state
    drain               Set durable mission lifecycle state
    resume              Set durable mission lifecycle state
    cancel              Set durable mission lifecycle state
    abandon             Set durable mission lifecycle state
    recover             Recover stopped harnesses without rerunning uncertain
                        effects
    why                 Explain blocked work, attempts, limits, and uncertain
                        effects
    configure           Set persistent runtime limits and evidence enforcement
    amend               Version a paused mission and require explicit
                        replanning
    effect              Track intent and receipts for external actions
    resource            Lease exclusive resources with attempt fencing
    evidence            Bind result files to criteria, revision, and
                        environment
    review-commit       Record a semantic disposition for every manager
                        trigger
    workspace           Create, register, or inspect task-specific isolated
                        checkouts
    serve               Poll durable service state with bounded restartable
                        scheduler runs
    audit-verify        Verify every manifest file in an audit ZIP
    init                Create a mission workspace
    demo                Run a synthetic example without configuring a harness
    status              Show the current canonical snapshot
    board               Regenerate the Markdown board
    report              Generate the executive workstream and action report
    reconcile           Apply deterministic readiness and lease transitions
    doctor              Check state invariants
    setup-check         Validate harness integration without launching an
                        agent
    ask                 Start a read-only briefing inquiry
    policy              Install and apply reusable workflow policy packs
    case                Manage idempotent work requests for persistent
                        services
    extension           Install delivery adapters for external systems
    delivery            Manage the durable external-delivery outbox
    workstream          Manage executive-level workstreams
    task                Manage tasks
    decision            Manage durable decisions
    finding             Elevate and disposition mission-relevant findings
    wait                Inspect and signal durable external waits
    fact                Record sourced, time-bounded operational facts
    inbox               Read a page of events since an agent cursor
    prompt              Generate a grounded role prompt
    dispatch            Invoke the configured third-party harness
    run                 Run manager/worker cycles through the configured
                        harness
    mission             Manage mission lifecycle
    export              Create a reviewable audit ZIP

optional arguments:
  -h, --help            show this help message and exit
  --root ROOT           Swarm workspace (default: $SWARM_ROOT or .swarm)
  --version             show program's version number and exit
```

## `swarmctl abandon`

```text
usage: swarmctl abandon [-h] --reason REASON [--actor ACTOR]

optional arguments:
  -h, --help       show this help message and exit
  --reason REASON
  --actor ACTOR
```

## `swarmctl amend`

```text
usage: swarmctl amend [-h] --objective OBJECTIVE [--success SUCCESS]
                      [--constraint CONSTRAINT] --reason REASON
                      [--actor ACTOR]

optional arguments:
  -h, --help            show this help message and exit
  --objective OBJECTIVE
  --success SUCCESS
  --constraint CONSTRAINT
  --reason REASON
  --actor ACTOR
```

## `swarmctl ask`

```text
usage: swarmctl ask [-h] --question QUESTION [--workstream WORKSTREAM]
                    [--case CASE] [--depends-on DEPENDS_ON] [--actor ACTOR]

optional arguments:
  -h, --help            show this help message and exit
  --question QUESTION
  --workstream WORKSTREAM
  --case CASE
  --depends-on DEPENDS_ON
  --actor ACTOR
```

## `swarmctl audit-verify`

```text
usage: swarmctl audit-verify [-h] archive

positional arguments:
  archive

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl board`

```text
usage: swarmctl board [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl cancel`

```text
usage: swarmctl cancel [-h] --reason REASON [--actor ACTOR]

optional arguments:
  -h, --help       show this help message and exit
  --reason REASON
  --actor ACTOR
```

## `swarmctl case`

```text
usage: swarmctl case [-h]
                     {open,list,show,apply-policy,link-task,signal,cancel} ...

positional arguments:
  {open,list,show,apply-policy,link-task,signal,cancel}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl case apply-policy`

```text
usage: swarmctl case apply-policy [-h] [--var VAR] [--ready] [--actor ACTOR]
                                  case_id policy_id

positional arguments:
  case_id
  policy_id

optional arguments:
  -h, --help     show this help message and exit
  --var VAR
  --ready
  --actor ACTOR
```

## `swarmctl case cancel`

```text
usage: swarmctl case cancel [-h] --reason REASON [--actor ACTOR] case_id

positional arguments:
  case_id

optional arguments:
  -h, --help       show this help message and exit
  --reason REASON
  --actor ACTOR
```

## `swarmctl case link-task`

```text
usage: swarmctl case link-task [-h] --task TASK [--actor ACTOR] case_id

positional arguments:
  case_id

optional arguments:
  -h, --help     show this help message and exit
  --task TASK
  --actor ACTOR
```

## `swarmctl case list`

```text
usage: swarmctl case list [-h]
                          [--status {ACTIVE,CANCELLED,DONE,OPEN,VERIFYING,WAITING_EXTERNAL,WAITING_HUMAN}]

optional arguments:
  -h, --help            show this help message and exit
  --status {ACTIVE,CANCELLED,DONE,OPEN,VERIFYING,WAITING_EXTERNAL,WAITING_HUMAN}
```

## `swarmctl case open`

```text
usage: swarmctl case open [-h] --source SOURCE --external-id EXTERNAL_ID
                          --title TITLE --objective OBJECTIVE
                          [--priority PRIORITY] [--acceptance ACCEPTANCE]
                          [--payload PAYLOAD] [--metadata METADATA]
                          [--policy POLICY] [--var VAR] [--ready]
                          [--actor ACTOR]

optional arguments:
  -h, --help            show this help message and exit
  --source SOURCE
  --external-id EXTERNAL_ID
  --title TITLE
  --objective OBJECTIVE
  --priority PRIORITY
  --acceptance ACCEPTANCE
  --payload PAYLOAD
  --metadata METADATA   Repeatable name=value
  --policy POLICY
  --var VAR             Policy value as name=value
  --ready
  --actor ACTOR
```

## `swarmctl case show`

```text
usage: swarmctl case show [-h] case_id

positional arguments:
  case_id

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl case signal`

```text
usage: swarmctl case signal [-h] --source SOURCE --external-id EXTERNAL_ID
                            --kind KIND [--author AUTHOR] --body BODY
                            [--payload PAYLOAD] [--metadata METADATA]
                            [--decision DECISION] [--wake] [--actor ACTOR]
                            case_id

positional arguments:
  case_id

optional arguments:
  -h, --help            show this help message and exit
  --source SOURCE
  --external-id EXTERNAL_ID
  --kind KIND
  --author AUTHOR
  --body BODY
  --payload PAYLOAD
  --metadata METADATA   Repeatable name=value
  --decision DECISION   Resolve this linked open decision with the signal body
  --wake                Create a ready follow-up task
  --actor ACTOR
```

## `swarmctl configure`

```text
usage: swarmctl configure [-h] [--limits LIMITS] [--strict-evidence {on,off}]

optional arguments:
  -h, --help            show this help message and exit
  --limits LIMITS       JSON limits object
  --strict-evidence {on,off}
```

## `swarmctl decision`

```text
usage: swarmctl decision [-h]
                         {list,show,resolve,revise,require-choice,link,ack}
                         ...

positional arguments:
  {list,show,resolve,revise,require-choice,link,ack}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl decision ack`

```text
usage: swarmctl decision ack [-h] --task TASK --agent AGENT decision_id

positional arguments:
  decision_id

optional arguments:
  -h, --help     show this help message and exit
  --task TASK
  --agent AGENT
```

## `swarmctl decision link`

```text
usage: swarmctl decision link [-h] --task TASK [--actor ACTOR] decision_id

positional arguments:
  decision_id

optional arguments:
  -h, --help     show this help message and exit
  --task TASK
  --actor ACTOR
```

## `swarmctl decision list`

```text
usage: swarmctl decision list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl decision require-choice`

```text
usage: swarmctl decision require-choice [-h] --choice CHOICE decision_id

positional arguments:
  decision_id

optional arguments:
  -h, --help       show this help message and exit
  --choice CHOICE
```

## `swarmctl decision resolve`

```text
usage: swarmctl decision resolve [-h] --answer ANSWER [--choice CHOICE]
                                 [--actor ACTOR]
                                 decision_id

positional arguments:
  decision_id

optional arguments:
  -h, --help       show this help message and exit
  --answer ANSWER
  --choice CHOICE  Exact machine-readable option from the decision
  --actor ACTOR
```

## `swarmctl decision revise`

```text
usage: swarmctl decision revise [-h] --answer ANSWER [--choice CHOICE]
                                [--actor ACTOR]
                                decision_id

positional arguments:
  decision_id

optional arguments:
  -h, --help       show this help message and exit
  --answer ANSWER
  --choice CHOICE  Exact machine-readable option from the decision
  --actor ACTOR
```

## `swarmctl decision show`

```text
usage: swarmctl decision show [-h] decision_id

positional arguments:
  decision_id

optional arguments:
  -h, --help   show this help message and exit
```

## `swarmctl delivery`

```text
usage: swarmctl delivery [-h]
                         {enqueue,enqueue-report,list,show,claim,sent,fail,retry,reconcile,cancel,dispatch}
                         ...

positional arguments:
  {enqueue,enqueue-report,list,show,claim,sent,fail,retry,reconcile,cancel,dispatch}
    enqueue             Snapshot an existing file and enqueue it
    enqueue-report      Generate the current status report and enqueue it
    reconcile           Record provider truth for an uncertain delivery

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl delivery cancel`

```text
usage: swarmctl delivery cancel [-h] [--actor ACTOR] --reason REASON
                                delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help       show this help message and exit
  --actor ACTOR
  --reason REASON
```

## `swarmctl delivery claim`

```text
usage: swarmctl delivery claim [-h] --agent AGENT
                               [--lease-seconds LEASE_SECONDS]
                               delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --lease-seconds LEASE_SECONDS
```

## `swarmctl delivery dispatch`

```text
usage: swarmctl delivery dispatch [-h] --agent AGENT [--dry-run] delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help     show this help message and exit
  --agent AGENT
  --dry-run
```

## `swarmctl delivery enqueue`

```text
usage: swarmctl delivery enqueue [-h] --extension EXTENSION --channel CHANNEL
                                 --subject SUBJECT --recipient RECIPIENT
                                 [--metadata METADATA] --idempotency-key
                                 IDEMPOTENCY_KEY [--actor ACTOR] --content
                                 CONTENT

optional arguments:
  -h, --help            show this help message and exit
  --extension EXTENSION
  --channel CHANNEL
  --subject SUBJECT
  --recipient RECIPIENT
  --metadata METADATA   Repeatable name=value
  --idempotency-key IDEMPOTENCY_KEY
  --actor ACTOR
  --content CONTENT
```

## `swarmctl delivery enqueue-report`

```text
usage: swarmctl delivery enqueue-report [-h] --extension EXTENSION --channel
                                        CHANNEL --subject SUBJECT --recipient
                                        RECIPIENT [--metadata METADATA]
                                        --idempotency-key IDEMPOTENCY_KEY
                                        [--actor ACTOR]

optional arguments:
  -h, --help            show this help message and exit
  --extension EXTENSION
  --channel CHANNEL
  --subject SUBJECT
  --recipient RECIPIENT
  --metadata METADATA   Repeatable name=value
  --idempotency-key IDEMPOTENCY_KEY
  --actor ACTOR
```

## `swarmctl delivery fail`

```text
usage: swarmctl delivery fail [-h] --agent AGENT --error ERROR delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help     show this help message and exit
  --agent AGENT
  --error ERROR
```

## `swarmctl delivery list`

```text
usage: swarmctl delivery list [-h]
                              [--status {CANCELLED,CLAIMED,FAILED,PENDING,SENT,UNKNOWN}]

optional arguments:
  -h, --help            show this help message and exit
  --status {CANCELLED,CLAIMED,FAILED,PENDING,SENT,UNKNOWN}
```

## `swarmctl delivery reconcile`

```text
usage: swarmctl delivery reconcile [-h] --outcome {sent,not-sent} --receipt
                                   RECEIPT [--actor ACTOR]
                                   delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help            show this help message and exit
  --outcome {sent,not-sent}
  --receipt RECEIPT
  --actor ACTOR
```

## `swarmctl delivery retry`

```text
usage: swarmctl delivery retry [-h] [--actor ACTOR] delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help     show this help message and exit
  --actor ACTOR
```

## `swarmctl delivery sent`

```text
usage: swarmctl delivery sent [-h] --agent AGENT --receipt RECEIPT delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help         show this help message and exit
  --agent AGENT
  --receipt RECEIPT
```

## `swarmctl delivery show`

```text
usage: swarmctl delivery show [-h] delivery_id

positional arguments:
  delivery_id

optional arguments:
  -h, --help   show this help message and exit
```

## `swarmctl demo`

```text
usage: swarmctl demo [-h] [--output OUTPUT]

optional arguments:
  -h, --help       show this help message and exit
  --output OUTPUT  Audit ZIP (default: ROOT/../audit.zip)
```

## `swarmctl dispatch`

```text
usage: swarmctl dispatch [-h] --role
                         {manager,worker,liaison,status,briefer,verifier}
                         --agent AGENT [--task TASK] [--dry-run]

optional arguments:
  -h, --help            show this help message and exit
  --role {manager,worker,liaison,status,briefer,verifier}
  --agent AGENT
  --task TASK
  --dry-run
```

## `swarmctl doctor`

```text
usage: swarmctl doctor [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl drain`

```text
usage: swarmctl drain [-h] --reason REASON [--actor ACTOR]

optional arguments:
  -h, --help       show this help message and exit
  --reason REASON
  --actor ACTOR
```

## `swarmctl effect`

```text
usage: swarmctl effect [-h]
                       {prepare,list,start,succeeded,failed,unknown,not-applied}
                       ...

positional arguments:
  {prepare,list,start,succeeded,failed,unknown,not-applied}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl effect failed`

```text
usage: swarmctl effect failed [-h] --actor ACTOR --receipt RECEIPT effect_id

positional arguments:
  effect_id

optional arguments:
  -h, --help         show this help message and exit
  --actor ACTOR
  --receipt RECEIPT
```

## `swarmctl effect list`

```text
usage: swarmctl effect list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl effect not-applied`

```text
usage: swarmctl effect not-applied [-h] --actor ACTOR --receipt RECEIPT
                                   effect_id

positional arguments:
  effect_id

optional arguments:
  -h, --help         show this help message and exit
  --actor ACTOR
  --receipt RECEIPT
```

## `swarmctl effect prepare`

```text
usage: swarmctl effect prepare [-h] --task TASK --agent AGENT --key KEY
                               --target TARGET --revision REVISION
                               [--parameters PARAMETERS]

optional arguments:
  -h, --help            show this help message and exit
  --task TASK
  --agent AGENT
  --key KEY
  --target TARGET
  --revision REVISION
  --parameters PARAMETERS
                        JSON action parameters
```

## `swarmctl effect start`

```text
usage: swarmctl effect start [-h] --actor ACTOR [--receipt RECEIPT] effect_id

positional arguments:
  effect_id

optional arguments:
  -h, --help         show this help message and exit
  --actor ACTOR
  --receipt RECEIPT
```

## `swarmctl effect succeeded`

```text
usage: swarmctl effect succeeded [-h] --actor ACTOR --receipt RECEIPT
                                 effect_id

positional arguments:
  effect_id

optional arguments:
  -h, --help         show this help message and exit
  --actor ACTOR
  --receipt RECEIPT
```

## `swarmctl effect unknown`

```text
usage: swarmctl effect unknown [-h] --actor ACTOR --receipt RECEIPT effect_id

positional arguments:
  effect_id

optional arguments:
  -h, --help         show this help message and exit
  --actor ACTOR
  --receipt RECEIPT
```

## `swarmctl evidence`

```text
usage: swarmctl evidence [-h] {contract,record,gaps} ...

positional arguments:
  {contract,record,gaps}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl evidence contract`

```text
usage: swarmctl evidence contract [-h] --task TASK --revision REVISION
                                  --environment ENVIRONMENT [--actor ACTOR]

optional arguments:
  -h, --help            show this help message and exit
  --task TASK
  --revision REVISION
  --environment ENVIRONMENT
  --actor ACTOR
```

## `swarmctl evidence gaps`

```text
usage: swarmctl evidence gaps [-h] --task TASK

optional arguments:
  -h, --help   show this help message and exit
  --task TASK
```

## `swarmctl evidence record`

```text
usage: swarmctl evidence record [-h] --task TASK --agent AGENT --criterion
                                CRITERION --revision REVISION --environment
                                ENVIRONMENT --command EVIDENCE_COMMAND_TEXT
                                --path PATH --exit-code EXIT_CODE

optional arguments:
  -h, --help            show this help message and exit
  --task TASK
  --agent AGENT
  --criterion CRITERION
  --revision REVISION
  --environment ENVIRONMENT
  --command EVIDENCE_COMMAND_TEXT
  --path PATH
  --exit-code EXIT_CODE
```

## `swarmctl export`

```text
usage: swarmctl export [-h] --output OUTPUT [--share-safe]
                       [--include-artifacts]
                       [--max-artifact-mb MAX_ARTIFACT_MB]

optional arguments:
  -h, --help            show this help message and exit
  --output OUTPUT
  --share-safe          Export only allowlisted structural telemetry,
                        excluding free text and files
  --include-artifacts
  --max-artifact-mb MAX_ARTIFACT_MB
```

## `swarmctl extension`

```text
usage: swarmctl extension [-h] {install,validate,list,show} ...

positional arguments:
  {install,validate,list,show}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl extension install`

```text
usage: swarmctl extension install [-h] [--actor ACTOR] [--force] source

positional arguments:
  source         Extension directory or extension.json path

optional arguments:
  -h, --help     show this help message and exit
  --actor ACTOR
  --force
```

## `swarmctl extension list`

```text
usage: swarmctl extension list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl extension show`

```text
usage: swarmctl extension show [-h] extension_id

positional arguments:
  extension_id

optional arguments:
  -h, --help    show this help message and exit
```

## `swarmctl extension validate`

```text
usage: swarmctl extension validate [-h] source

positional arguments:
  source      Extension directory or extension.json path

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl fact`

```text
usage: swarmctl fact [-h] {list,record} ...

positional arguments:
  {list,record}

optional arguments:
  -h, --help     show this help message and exit
```

## `swarmctl fact list`

```text
usage: swarmctl fact list [-h] [--include-expired]

optional arguments:
  -h, --help         show this help message and exit
  --include-expired
```

## `swarmctl fact record`

```text
usage: swarmctl fact record [-h] --subject SUBJECT --value VALUE --source
                            SOURCE --actor ACTOR [--task TASK]
                            [--observed-at OBSERVED_AT]
                            [--expires-at EXPIRES_AT]
                            [--ttl-seconds TTL_SECONDS]

optional arguments:
  -h, --help            show this help message and exit
  --subject SUBJECT
  --value VALUE
  --source SOURCE
  --actor ACTOR
  --task TASK
  --observed-at OBSERVED_AT
  --expires-at EXPIRES_AT
  --ttl-seconds TTL_SECONDS
```

## `swarmctl finding`

```text
usage: swarmctl finding [-h] {raise,list,show,disposition} ...

positional arguments:
  {raise,list,show,disposition}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl finding disposition`

```text
usage: swarmctl finding disposition [-h] --status
                                    {DEFERRED,DISMISSED,INCORPORATED}
                                    --rationale RATIONALE [--task TASK]
                                    [--workstream WORKSTREAM] [--actor ACTOR]
                                    finding_id

positional arguments:
  finding_id

optional arguments:
  -h, --help            show this help message and exit
  --status {DEFERRED,DISMISSED,INCORPORATED}
  --rationale RATIONALE
  --task TASK
  --workstream WORKSTREAM
  --actor ACTOR
```

## `swarmctl finding list`

```text
usage: swarmctl finding list [-h]
                             [--status {DEFERRED,DISMISSED,INCORPORATED,OPEN}]
                             [--significance {MATERIAL,ROUTINE,URGENT}]

optional arguments:
  -h, --help            show this help message and exit
  --status {DEFERRED,DISMISSED,INCORPORATED,OPEN}
  --significance {MATERIAL,ROUTINE,URGENT}
```

## `swarmctl finding raise`

```text
usage: swarmctl finding raise [-h] --task TASK --agent AGENT --significance
                              {MATERIAL,ROUTINE,URGENT} --summary SUMMARY
                              --evidence EVIDENCE --impact IMPACT
                              [--recommendation RECOMMENDATION]

optional arguments:
  -h, --help            show this help message and exit
  --task TASK
  --agent AGENT
  --significance {MATERIAL,ROUTINE,URGENT}
  --summary SUMMARY
  --evidence EVIDENCE
  --impact IMPACT
  --recommendation RECOMMENDATION
```

## `swarmctl finding show`

```text
usage: swarmctl finding show [-h] finding_id

positional arguments:
  finding_id

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl inbox`

```text
usage: swarmctl inbox [-h] --agent AGENT [--task TASK] [--after AFTER]
                      [--advance] [--lease] [--ack ACK] [--limit LIMIT]
                      [--lease-seconds LEASE_SECONDS]

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --task TASK           Limit events to one task and its dependencies
  --after AFTER
  --advance             Legacy read-and-advance; use --lease and --ack for
                        reliable delivery
  --lease
  --ack ACK             Acknowledge a leased delivery token
  --limit LIMIT
  --lease-seconds LEASE_SECONDS
```

## `swarmctl init`

```text
usage: swarmctl init [-h] --objective OBJECTIVE [--success SUCCESS]
                     [--constraint CONSTRAINT] [--mode {FINITE,SERVICE}]

optional arguments:
  -h, --help            show this help message and exit
  --objective OBJECTIVE
  --success SUCCESS     Repeatable success condition
  --constraint CONSTRAINT
                        Repeatable safety or scope boundary
  --mode {FINITE,SERVICE}
                        FINITE completes once; SERVICE remains available for
                        durable cases
```

## `swarmctl mission`

```text
usage: swarmctl mission [-h] {phase,complete} ...

positional arguments:
  {phase,complete}

optional arguments:
  -h, --help        show this help message and exit
```

## `swarmctl mission complete`

```text
usage: swarmctl mission complete [-h] --evidence EVIDENCE [--actor ACTOR]
                                 [--shutdown-service]
                                 [--outcome {SUCCEEDED,PARTIAL}]

optional arguments:
  -h, --help            show this help message and exit
  --evidence EVIDENCE
  --actor ACTOR
  --shutdown-service
  --outcome {SUCCEEDED,PARTIAL}
                        Default: PARTIAL if any tasks were cancelled,
                        otherwise SUCCEEDED
```

## `swarmctl mission phase`

```text
usage: swarmctl mission phase [-h] [--actor ACTOR] phase

positional arguments:
  phase

optional arguments:
  -h, --help     show this help message and exit
  --actor ACTOR
```

## `swarmctl pause`

```text
usage: swarmctl pause [-h] --reason REASON [--actor ACTOR]

optional arguments:
  -h, --help       show this help message and exit
  --reason REASON
  --actor ACTOR
```

## `swarmctl policy`

```text
usage: swarmctl policy [-h]
                       {install,validate,list,show,apply,applications,application}
                       ...

positional arguments:
  {install,validate,list,show,apply,applications,application}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl policy application`

```text
usage: swarmctl policy application [-h] application_id

positional arguments:
  application_id

optional arguments:
  -h, --help      show this help message and exit
```

## `swarmctl policy applications`

```text
usage: swarmctl policy applications [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl policy apply`

```text
usage: swarmctl policy apply [-h] [--var VAR] [--workstream WORKSTREAM]
                             [--actor ACTOR] [--ready]
                             policy_id

positional arguments:
  policy_id

optional arguments:
  -h, --help            show this help message and exit
  --var VAR             Template value as name=value
  --workstream WORKSTREAM
  --actor ACTOR
  --ready               Authorize all generated stages
```

## `swarmctl policy install`

```text
usage: swarmctl policy install [-h] [--actor ACTOR] [--force] source

positional arguments:
  source         Policy directory or policy.json path

optional arguments:
  -h, --help     show this help message and exit
  --actor ACTOR
  --force
```

## `swarmctl policy list`

```text
usage: swarmctl policy list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl policy show`

```text
usage: swarmctl policy show [-h] policy_id

positional arguments:
  policy_id

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl policy validate`

```text
usage: swarmctl policy validate [-h] source

positional arguments:
  source      Policy directory or policy.json path

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl prompt`

```text
usage: swarmctl prompt [-h] --role
                       {manager,worker,liaison,status,briefer,verifier}
                       --agent AGENT [--task TASK] [--write]

optional arguments:
  -h, --help            show this help message and exit
  --role {manager,worker,liaison,status,briefer,verifier}
  --agent AGENT
  --task TASK
  --write
```

## `swarmctl reconcile`

```text
usage: swarmctl reconcile [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl recover`

```text
usage: swarmctl recover [-h] [--abandon-run ABANDON_RUN] [--reason REASON]
                        [--actor ACTOR]

optional arguments:
  -h, --help            show this help message and exit
  --abandon-run ABANDON_RUN
  --reason REASON
  --actor ACTOR
```

## `swarmctl report`

```text
usage: swarmctl report [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl resource`

```text
usage: swarmctl resource [-h] {acquire,release,list} ...

positional arguments:
  {acquire,release,list}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl resource acquire`

```text
usage: swarmctl resource acquire [-h] --task TASK --agent AGENT
                                 [--lease-seconds LEASE_SECONDS]
                                 resource

positional arguments:
  resource

optional arguments:
  -h, --help            show this help message and exit
  --task TASK
  --agent AGENT
  --lease-seconds LEASE_SECONDS
```

## `swarmctl resource list`

```text
usage: swarmctl resource list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl resource release`

```text
usage: swarmctl resource release [-h] --agent AGENT token

positional arguments:
  token

optional arguments:
  -h, --help     show this help message and exit
  --agent AGENT
```

## `swarmctl resume`

```text
usage: swarmctl resume [-h] --reason REASON [--actor ACTOR]

optional arguments:
  -h, --help       show this help message and exit
  --reason REASON
  --actor ACTOR
```

## `swarmctl review-commit`

```text
usage: swarmctl review-commit [-h] --agent AGENT --dispositions DISPOSITIONS
                              --summary SUMMARY
                              review_id

positional arguments:
  review_id

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --dispositions DISPOSITIONS
                        JSON list in trigger order
  --summary SUMMARY
```

## `swarmctl run`

```text
usage: swarmctl run [-h] [--max-cycles MAX_CYCLES] [--dry-run]

optional arguments:
  -h, --help            show this help message and exit
  --max-cycles MAX_CYCLES
  --dry-run
```

## `swarmctl serve`

```text
usage: swarmctl serve [-h] [--max-polls MAX_POLLS]
                      [--poll-seconds POLL_SECONDS] [--max-cycles MAX_CYCLES]

optional arguments:
  -h, --help            show this help message and exit
  --max-polls MAX_POLLS
  --poll-seconds POLL_SECONDS
  --max-cycles MAX_CYCLES
```

## `swarmctl setup-check`

```text
usage: swarmctl setup-check [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl status`

```text
usage: swarmctl status [-h] [--brief]

optional arguments:
  -h, --help  show this help message and exit
  --brief     Show a short human-readable summary
```

## `swarmctl task`

```text
usage: swarmctl task [-h]
                     {add,approve,claim,checkpoint,complete,cancel,block,wait-external,list,show}
                     ...

positional arguments:
  {add,approve,claim,checkpoint,complete,cancel,block,wait-external,list,show}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl task add`

```text
usage: swarmctl task add [-h] [--idempotency-key IDEMPOTENCY_KEY] --title
                         TITLE --description DESCRIPTION --kind
                         {briefing,discovery,implementation,verification}
                         --acceptance ACCEPTANCE [--depends-on DEPENDS_ON]
                         [--workstream WORKSTREAM] [--priority PRIORITY]
                         [--actor ACTOR] [--ready]

optional arguments:
  -h, --help            show this help message and exit
  --idempotency-key IDEMPOTENCY_KEY
  --title TITLE
  --description DESCRIPTION
  --kind {briefing,discovery,implementation,verification}
  --acceptance ACCEPTANCE
  --depends-on DEPENDS_ON
  --workstream WORKSTREAM
                        Executive workstream that owns this task
  --priority PRIORITY
  --actor ACTOR
  --ready               Authorize immediately
```

## `swarmctl task approve`

```text
usage: swarmctl task approve [-h] [--actor ACTOR] task_id

positional arguments:
  task_id

optional arguments:
  -h, --help     show this help message and exit
  --actor ACTOR
```

## `swarmctl task block`

```text
usage: swarmctl task block [-h] --agent AGENT --kind
                           {external_dependency,human_decision,missing_access,resource_conflict,safety_stop,technical_failure}
                           --question QUESTION
                           [--recommendation RECOMMENDATION] [--option OPTION]
                           task_id

positional arguments:
  task_id

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --kind {external_dependency,human_decision,missing_access,resource_conflict,safety_stop,technical_failure}
  --question QUESTION
  --recommendation RECOMMENDATION
  --option OPTION
```

## `swarmctl task cancel`

```text
usage: swarmctl task cancel [-h] [--actor ACTOR] --reason REASON task_id

positional arguments:
  task_id

optional arguments:
  -h, --help       show this help message and exit
  --actor ACTOR
  --reason REASON
```

## `swarmctl task checkpoint`

```text
usage: swarmctl task checkpoint [-h] --agent AGENT --summary SUMMARY
                                --next-action NEXT_ACTION
                                [--lease-seconds LEASE_SECONDS]
                                task_id

positional arguments:
  task_id

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --summary SUMMARY
  --next-action NEXT_ACTION
  --lease-seconds LEASE_SECONDS
```

## `swarmctl task claim`

```text
usage: swarmctl task claim [-h] --agent AGENT [--lease-seconds LEASE_SECONDS]
                           task_id

positional arguments:
  task_id

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --lease-seconds LEASE_SECONDS
```

## `swarmctl task complete`

```text
usage: swarmctl task complete [-h] --agent AGENT --result RESULT
                              --verification VERIFICATION
                              [--artifact ARTIFACT]
                              task_id

positional arguments:
  task_id

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --result RESULT
  --verification VERIFICATION
  --artifact ARTIFACT
```

## `swarmctl task list`

```text
usage: swarmctl task list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl task show`

```text
usage: swarmctl task show [-h] task_id

positional arguments:
  task_id

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl task wait-external`

```text
usage: swarmctl task wait-external [-h] --agent AGENT --condition CONDITION
                                   --external-ref EXTERNAL_REF
                                   [--next-check-at NEXT_CHECK_AT] --deadline
                                   DEADLINE [--signal-expected]
                                   task_id

positional arguments:
  task_id

optional arguments:
  -h, --help            show this help message and exit
  --agent AGENT
  --condition CONDITION
  --external-ref EXTERNAL_REF
  --next-check-at NEXT_CHECK_AT
  --deadline DEADLINE
  --signal-expected
```

## `swarmctl wait`

```text
usage: swarmctl wait [-h] {list,show,signal} ...

positional arguments:
  {list,show,signal}

optional arguments:
  -h, --help          show this help message and exit
```

## `swarmctl wait list`

```text
usage: swarmctl wait list [-h] [--status {CANCELLED,WAITING,WOKEN}]

optional arguments:
  -h, --help            show this help message and exit
  --status {CANCELLED,WAITING,WOKEN}
```

## `swarmctl wait show`

```text
usage: swarmctl wait show [-h] wait_id

positional arguments:
  wait_id

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl wait signal`

```text
usage: swarmctl wait signal [-h] --source SOURCE --external-id EXTERNAL_ID
                            [--note NOTE] [--actor ACTOR]
                            wait_id

positional arguments:
  wait_id

optional arguments:
  -h, --help            show this help message and exit
  --source SOURCE
  --external-id EXTERNAL_ID
  --note NOTE
  --actor ACTOR
```

## `swarmctl why`

```text
usage: swarmctl why [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl workspace`

```text
usage: swarmctl workspace [-h] {create,register,list} ...

positional arguments:
  {create,register,list}
    register            Register a checkout created by the harness or an
                        external tool

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl workspace create`

```text
usage: swarmctl workspace create [-h] --task TASK --repository REPOSITORY
                                 --base BASE [--provider {git,command,manual}]

optional arguments:
  -h, --help            show this help message and exit
  --task TASK
  --repository REPOSITORY
  --base BASE           Provider-specific base revision expression
  --provider {git,command,manual}
                        Override runner.json workspace provider
```

## `swarmctl workspace list`

```text
usage: swarmctl workspace list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl workspace register`

```text
usage: swarmctl workspace register [-h] --task TASK --repository REPOSITORY
                                   --path PATH --base-revision BASE_REVISION
                                   [--workspace-ref WORKSPACE_REF]
                                   [--agent AGENT]

optional arguments:
  -h, --help            show this help message and exit
  --task TASK
  --repository REPOSITORY
                        Source directory; no VCS metadata required
  --path PATH           Existing isolated checkout directory
  --base-revision BASE_REVISION
                        Exact provider-specific revision identifier
  --workspace-ref WORKSPACE_REF
                        Optional jj workspace name, branch, or internal
                        checkout reference
  --agent AGENT         Required when registering for an active task attempt
```

## `swarmctl workstream`

```text
usage: swarmctl workstream [-h] {add,update,link-task,list,show} ...

positional arguments:
  {add,update,link-task,list,show}

optional arguments:
  -h, --help            show this help message and exit
```

## `swarmctl workstream add`

```text
usage: swarmctl workstream add [-h] --name NAME --outcome OUTCOME
                               [--status {ACTIVE,BLOCKED,CANCELLED,DONE,PLANNED,VERIFYING}]
                               [--actor ACTOR]

optional arguments:
  -h, --help            show this help message and exit
  --name NAME
  --outcome OUTCOME
  --status {ACTIVE,BLOCKED,CANCELLED,DONE,PLANNED,VERIFYING}
  --actor ACTOR
```

## `swarmctl workstream link-task`

```text
usage: swarmctl workstream link-task [-h] --task TASK [--actor ACTOR]
                                     workstream_id

positional arguments:
  workstream_id

optional arguments:
  -h, --help     show this help message and exit
  --task TASK
  --actor ACTOR
```

## `swarmctl workstream list`

```text
usage: swarmctl workstream list [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl workstream show`

```text
usage: swarmctl workstream show [-h] workstream_id

positional arguments:
  workstream_id

optional arguments:
  -h, --help     show this help message and exit
```

## `swarmctl workstream update`

```text
usage: swarmctl workstream update [-h]
                                  [--status {ACTIVE,BLOCKED,CANCELLED,DONE,PLANNED,VERIFYING}]
                                  [--summary SUMMARY]
                                  [--forecast-earliest FORECAST_EARLIEST]
                                  [--forecast-latest FORECAST_LATEST]
                                  [--forecast-confidence {high,low,medium}]
                                  [--forecast-basis FORECAST_BASIS]
                                  [--actor ACTOR]
                                  workstream_id

positional arguments:
  workstream_id

optional arguments:
  -h, --help            show this help message and exit
  --status {ACTIVE,BLOCKED,CANCELLED,DONE,PLANNED,VERIFYING}
  --summary SUMMARY
  --forecast-earliest FORECAST_EARLIEST
  --forecast-latest FORECAST_LATEST
  --forecast-confidence {high,low,medium}
  --forecast-basis FORECAST_BASIS
  --actor ACTOR
```
