# CLI reference

Generated from `swarmctl.py` for version `0.6.0`. Do not edit by hand; run `python3 scripts/generate_cli_docs.py`.

## `swarmctl`

```text
usage: swarmctl [-h] [--root ROOT] [--version]
                {init,status,board,report,reconcile,doctor,setup-check,ask,policy,case,extension,delivery,workstream,task,decision,finding,wait,fact,inbox,prompt,dispatch,run,mission,export}
                ...

Durable, harness-neutral orchestration for ambiguous multi-agent work.

positional arguments:
  {init,status,board,report,reconcile,doctor,setup-check,ask,policy,case,extension,delivery,workstream,task,decision,finding,wait,fact,inbox,prompt,dispatch,run,mission,export}
    init                Create a mission workspace
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
    inbox               Read all events since an agent cursor
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

## `swarmctl board`

```text
usage: swarmctl board [-h]

optional arguments:
  -h, --help  show this help message and exit
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

## `swarmctl decision`

```text
usage: swarmctl decision [-h]
                         {list,resolve,revise,require-choice,link,ack} ...

positional arguments:
  {list,resolve,revise,require-choice,link,ack}

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

## `swarmctl delivery`

```text
usage: swarmctl delivery [-h]
                         {enqueue,enqueue-report,list,show,claim,sent,fail,retry,cancel,dispatch}
                         ...

positional arguments:
  {enqueue,enqueue-report,list,show,claim,sent,fail,retry,cancel,dispatch}
    enqueue             Snapshot an existing file and enqueue it
    enqueue-report      Generate the current status report and enqueue it

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
                              [--status {CANCELLED,CLAIMED,FAILED,PENDING,SENT}]

optional arguments:
  -h, --help            show this help message and exit
  --status {CANCELLED,CLAIMED,FAILED,PENDING,SENT}
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

## `swarmctl export`

```text
usage: swarmctl export [-h] --output OUTPUT [--include-artifacts]
                       [--max-artifact-mb MAX_ARTIFACT_MB]

optional arguments:
  -h, --help            show this help message and exit
  --output OUTPUT
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
                      [--advance]

optional arguments:
  -h, --help     show this help message and exit
  --agent AGENT
  --task TASK    Limit events to one task and its dependencies
  --after AFTER
  --advance
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

optional arguments:
  -h, --help           show this help message and exit
  --evidence EVIDENCE
  --actor ACTOR
  --shutdown-service
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

## `swarmctl report`

```text
usage: swarmctl report [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl run`

```text
usage: swarmctl run [-h] [--max-cycles MAX_CYCLES] [--dry-run]

optional arguments:
  -h, --help            show this help message and exit
  --max-cycles MAX_CYCLES
  --dry-run
```

## `swarmctl setup-check`

```text
usage: swarmctl setup-check [-h]

optional arguments:
  -h, --help  show this help message and exit
```

## `swarmctl status`

```text
usage: swarmctl status [-h]

optional arguments:
  -h, --help  show this help message and exit
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
usage: swarmctl task add [-h] --title TITLE --description DESCRIPTION --kind
                         {briefing,discovery,implementation,verification}
                         --acceptance ACCEPTANCE [--depends-on DEPENDS_ON]
                         [--workstream WORKSTREAM] [--priority PRIORITY]
                         [--actor ACTOR] [--ready]

optional arguments:
  -h, --help            show this help message and exit
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
