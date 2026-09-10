"""SQLite schema and sequential migrations. Existing databases upgrade atomically."""

from .core import (
    completion_outcome,
    SCHEMA_VERSION,
    SwarmError,
    VERSION,
    json_dump,
    json_load,
    make_id,
    utcnow,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    success_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'DISCOVERY',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    completion_evidence TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workstreams (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PLANNED',
    progress_summary TEXT,
    forecast_earliest TEXT,
    forecast_latest TEXT,
    forecast_confidence TEXT,
    forecast_basis TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PROPOSED',
    priority INTEGER NOT NULL DEFAULT 50,
    authorized INTEGER NOT NULL DEFAULT 0,
    acceptance_json TEXT NOT NULL,
    owner TEXT,
    lease_until TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    last_checkpoint_at TEXT,
    checkpoint_summary TEXT,
    next_action TEXT,
    result TEXT,
    verification_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    PRIMARY KEY (task_id, depends_on),
    CHECK (task_id <> depends_on)
);
CREATE TABLE IF NOT EXISTS task_workstreams (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    workstream_id TEXT NOT NULL REFERENCES workstreams(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS policy_packs (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    when_to_use TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    guidance_text TEXT NOT NULL,
    source_path TEXT NOT NULL,
    installed_by TEXT NOT NULL,
    installed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_applications (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    policy_id TEXT NOT NULL REFERENCES policy_packs(id) ON DELETE RESTRICT,
    policy_version TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    guidance_text TEXT NOT NULL,
    variables_json TEXT NOT NULL,
    workstream_id TEXT REFERENCES workstreams(id) ON DELETE SET NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_application_tasks (
    application_id TEXT NOT NULL REFERENCES policy_applications(id) ON DELETE CASCADE,
    stage_id TEXT NOT NULL,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    fresh_session_from TEXT,
    PRIMARY KEY (application_id, stage_id)
);
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    priority INTEGER NOT NULL DEFAULT 50,
    workstream_id TEXT NOT NULL REFERENCES workstreams(id) ON DELETE RESTRICT,
    policy_application_id TEXT REFERENCES policy_applications(id) ON DELETE SET NULL,
    payload_path TEXT,
    payload_sha256 TEXT,
    payload_size_bytes INTEGER,
    metadata_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    result_summary TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    UNIQUE (mission_id, source, external_id)
);
CREATE TABLE IF NOT EXISTS case_tasks (
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (case_id, task_id)
);
CREATE TABLE IF NOT EXISTS case_signals (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    author TEXT,
    body TEXT NOT NULL,
    payload_path TEXT,
    payload_sha256 TEXT,
    payload_size_bytes INTEGER,
    metadata_json TEXT NOT NULL,
    resolves_decision_id TEXT REFERENCES decisions(id) ON DELETE SET NULL,
    recorded_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, source, external_id)
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    source_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    significance TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    mission_impact TEXT NOT NULL,
    recommendation TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    disposition_rationale TEXT,
    disposed_by TEXT,
    disposed_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finding_tasks (
    finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    PRIMARY KEY (finding_id, task_id)
);
CREATE TABLE IF NOT EXISTS finding_workstreams (
    finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    workstream_id TEXT NOT NULL REFERENCES workstreams(id) ON DELETE RESTRICT,
    PRIMARY KEY (finding_id, workstream_id)
);
CREATE TABLE IF NOT EXISTS external_waits (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    condition TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    next_check_at TEXT,
    deadline_at TEXT NOT NULL,
    signal_expected INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'WAITING',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    woke_at TEXT,
    wake_reason TEXT,
    wake_source TEXT,
    wake_external_id TEXT,
    wake_note TEXT
);
CREATE TABLE IF NOT EXISTS wait_signals (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    wait_id TEXT NOT NULL REFERENCES external_waits(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    note TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, source, external_id)
);
CREATE TABLE IF NOT EXISTS manager_reviews (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    urgency TEXT NOT NULL DEFAULT 'NORMAL',
    triggers_json TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    owner TEXT,
    lease_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extensions (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    handles_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    guidance_text TEXT NOT NULL,
    source_path TEXT NOT NULL,
    installed_by TEXT NOT NULL,
    installed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    extension_id TEXT NOT NULL REFERENCES extensions(id) ON DELETE RESTRICT,
    extension_version TEXT NOT NULL,
    extension_manifest_json TEXT NOT NULL,
    extension_guidance_text TEXT NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT NOT NULL,
    recipients_json TEXT NOT NULL,
    content_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    content_size_bytes INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    claimed_by TEXT,
    lease_until TEXT,
    provider_receipt TEXT,
    last_error TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS delivery_runs (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    delivery_id TEXT NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    extension_id TEXT NOT NULL REFERENCES extensions(id) ON DELETE RESTRICT,
    executor_type TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    prompt_path TEXT,
    envelope_path TEXT NOT NULL,
    command_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    exit_code INTEGER,
    stdout_path TEXT,
    stderr_path TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    question TEXT NOT NULL,
    recommendation TEXT,
    options_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    answer TEXT,
    requested_by TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_tasks (
    decision_id TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (decision_id, task_id)
);
CREATE TABLE IF NOT EXISTS decision_acks (
    decision_id TEXT NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL,
    PRIMARY KEY (decision_id, task_id)
);
CREATE TABLE IF NOT EXISTS decision_outcomes (
    decision_id TEXT PRIMARY KEY REFERENCES decisions(id) ON DELETE CASCADE,
    selected_option TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    subject TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'CURRENT',
    recorded_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cursors (
    agent_id TEXT PRIMARY KEY,
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    sha256 TEXT,
    size_bytes INTEGER,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    agent_id TEXT NOT NULL,
    prompt_path TEXT NOT NULL,
    command_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    exit_code INTEGER,
    stdout_path TEXT,
    stderr_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, authorized, priority);
CREATE INDEX IF NOT EXISTS idx_workstreams_status ON workstreams(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_task_workstreams_workstream ON task_workstreams(workstream_id);
CREATE INDEX IF NOT EXISTS idx_policy_applications_policy ON policy_applications(policy_id, created_at);
CREATE INDEX IF NOT EXISTS idx_policy_application_tasks_task ON policy_application_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_case_tasks_case ON case_tasks(case_id);
CREATE INDEX IF NOT EXISTS idx_case_signals_case ON case_signals(case_id, created_at);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, significance, created_at);
CREATE INDEX IF NOT EXISTS idx_findings_task ON findings(source_task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_external_waits_task ON external_waits(task_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_external_waits_active_task
    ON external_waits(task_id) WHERE status='WAITING';
CREATE INDEX IF NOT EXISTS idx_external_waits_due
    ON external_waits(status, next_check_at, deadline_at);
CREATE INDEX IF NOT EXISTS idx_wait_signals_wait ON wait_signals(wait_id, created_at);
CREATE INDEX IF NOT EXISTS idx_manager_reviews_status
    ON manager_reviews(status, urgency, requested_at);
CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(status, created_at);
CREATE INDEX IF NOT EXISTS idx_delivery_runs_delivery ON delivery_runs(delivery_id, started_at);
CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject, status);
"""


RUNTIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_state (
    id INTEGER PRIMARY KEY CHECK(id=1), desired_state TEXT NOT NULL DEFAULT 'ACTIVE',
    revision INTEGER NOT NULL DEFAULT 1, outcome TEXT, reason TEXT,
    limits_json TEXT NOT NULL DEFAULT '{}', strict_evidence INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO runtime_state(id) VALUES(1);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), generation INTEGER NOT NULL,
    agent TEXT NOT NULL, state TEXT NOT NULL, mission_revision INTEGER NOT NULL,
    started_at TEXT NOT NULL, ended_at TEXT, reason TEXT,
    UNIQUE(task_id, generation), UNIQUE(task_id, agent)
);
CREATE TABLE IF NOT EXISTS effects (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    generation INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
    target TEXT NOT NULL, revision TEXT NOT NULL, parameters_json TEXT NOT NULL,
    state TEXT NOT NULL, receipt TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox_deliveries (
    token TEXT PRIMARY KEY, agent TEXT NOT NULL, scope TEXT NOT NULL,
    start_seq INTEGER NOT NULL, end_seq INTEGER NOT NULL, payload_json TEXT NOT NULL,
    lease_until TEXT NOT NULL, acked_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_active ON inbox_deliveries(agent, scope) WHERE acked_at IS NULL;
CREATE TABLE IF NOT EXISTS inbox_offsets (
    agent TEXT NOT NULL, scope TEXT NOT NULL, last_seq INTEGER NOT NULL,
    PRIMARY KEY(agent, scope)
);
CREATE TABLE IF NOT EXISTS resource_leases (
    resource TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    generation INTEGER NOT NULL, token TEXT NOT NULL UNIQUE, lease_until TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), generation INTEGER NOT NULL,
    mission_revision INTEGER NOT NULL, criterion TEXT NOT NULL, revision TEXT NOT NULL,
    environment TEXT NOT NULL, command TEXT NOT NULL, exit_code INTEGER NOT NULL,
    path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_contracts (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id), revision TEXT NOT NULL, environment TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_keys (
    key TEXT PRIMARY KEY, specification TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS mission_amendments (
    revision INTEGER PRIMARY KEY, previous_json TEXT NOT NULL, current_json TEXT NOT NULL,
    reason TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_commits (
    review_id TEXT PRIMARY KEY REFERENCES manager_reviews(id), actor TEXT NOT NULL,
    dispositions_json TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id), path TEXT NOT NULL UNIQUE,
    repository TEXT NOT NULL, base_revision TEXT NOT NULL, branch TEXT NOT NULL
);
"""


CONTEXT_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_agent_runs_unfinished ON agent_runs(id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_delivery_runs_unfinished ON delivery_runs(id) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS policy_application_keys (
    key TEXT PRIMARY KEY,
    specification TEXT NOT NULL,
    application_id TEXT NOT NULL UNIQUE REFERENCES policy_applications(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS case_signal_tasks (
    signal_id TEXT PRIMARY KEY REFERENCES case_signals(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_entity_seq ON events(entity_id, seq);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_task ON agent_runs(task_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_decision_tasks_task ON decision_tasks(task_id, decision_id);
CREATE INDEX IF NOT EXISTS idx_finding_tasks_task ON finding_tasks(task_id, finding_id);
CREATE INDEX IF NOT EXISTS idx_facts_task ON facts(task_id);
CREATE INDEX IF NOT EXISTS idx_effects_task ON effects(task_id, state);
CREATE INDEX IF NOT EXISTS idx_attempts_agent ON attempts(task_id, agent);
"""


WORKSPACE_CREATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_creations (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    repository TEXT NOT NULL, requested_base TEXT NOT NULL, provider TEXT NOT NULL,
    suggested_path TEXT NOT NULL, state TEXT NOT NULL
        CHECK(state IN ('UNKNOWN','CREATED','REGISTERED','NOT_CREATED')),
    command_json TEXT NOT NULL, receipt_json TEXT, observation TEXT,
    stdout_path TEXT NOT NULL, stderr_path TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_creation_pending
    ON workspace_creations(task_id) WHERE state IN ('UNKNOWN','CREATED');
CREATE INDEX IF NOT EXISTS idx_workspace_creation_task ON workspace_creations(task_id,created_at);
"""


REVIEW_BATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS manager_review_trigger_keys (
    review_id TEXT NOT NULL REFERENCES manager_reviews(id) ON DELETE CASCADE,
    reason TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    PRIMARY KEY(review_id,reason,entity_type,entity_id)
);
CREATE INDEX IF NOT EXISTS idx_review_trigger_identity
    ON manager_review_trigger_keys(reason,entity_type,entity_id,review_id);
CREATE INDEX IF NOT EXISTS idx_review_requested ON manager_reviews(status,requested_at);
"""


EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_record_keys (
    task_id TEXT NOT NULL REFERENCES tasks(id), key TEXT NOT NULL,
    evidence_id TEXT NOT NULL UNIQUE REFERENCES evidence(id),
    PRIMARY KEY(task_id,key)
);
CREATE INDEX IF NOT EXISTS idx_evidence_target
    ON evidence(task_id,criterion,generation,mission_revision,revision,environment);
CREATE INDEX IF NOT EXISTS idx_evidence_criterion ON evidence(task_id,criterion);
CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence(task_id);
"""


def migrate_review_batches(conn):
    execute_schema(conn, REVIEW_BATCH_SCHEMA)
    # Keep legacy review payloads/order intact. The table is an identity index;
    # triggers_json remains the ordered review contract and audit payload.
    for review in conn.execute("SELECT id,triggers_json FROM manager_reviews"):
        for trigger in json_load(review["triggers_json"], []):
            conn.execute(
                "INSERT OR IGNORE INTO manager_review_trigger_keys VALUES(?,?,?,?)",
                (review["id"], trigger["reason"], trigger["entity_type"], trigger["entity_id"]),
            )


def execute_schema(conn, source):
    # executescript commits implicitly; execute each DDL statement in our transaction.
    for statement in source.split(";"):
        if statement.strip():
            conn.execute(statement)


def migrate_workspace_schema(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(workspaces)")}
    if "provider" not in columns:
        conn.execute("ALTER TABLE workspaces ADD COLUMN provider TEXT NOT NULL DEFAULT 'git'")
    if "requested_base" not in columns:
        conn.execute("ALTER TABLE workspaces ADD COLUMN requested_base TEXT")


def migrate_reliability_schema(conn):
    execute_schema(conn, CONTEXT_SCHEMA)
    # The old wakeup identity lived in prose. Recover the actual relationship
    # from the structured creation event, even if a task description was edited.
    for event in conn.execute(
        "SELECT entity_id,payload_json FROM events WHERE event_type='CASE_WOKEN' ORDER BY seq"
    ):
        payload = json_load(event[1], {})
        conn.execute(
            """INSERT OR IGNORE INTO case_signal_tasks(signal_id,task_id)
               SELECT s.id,t.id FROM case_signals s JOIN case_tasks ct ON ct.case_id=s.case_id
               JOIN tasks t ON t.id=ct.task_id
               WHERE s.id=? AND t.id=? AND s.case_id=?""",
            (payload.get("signal_id"), payload.get("task_id"), event[0]),
        )
    for table in ("cases", "workstreams"):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")}
        if "completion_outcome" not in columns:
            conn.execute("ALTER TABLE " + table + " ADD COLUMN completion_outcome TEXT")
    # Only explicit case cancellation is permanent. An exhausted intake plan may
    # be replaced by new work without reopening a cancelled user request.
    mission_cancelled = conn.execute(
        "SELECT 1 FROM runtime_state WHERE desired_state IN ('CANCELLED','ABANDONED')"
    ).fetchone()
    for case in conn.execute(
        "SELECT id,status,workstream_id FROM cases WHERE status IN ('DONE','CANCELLED')"
    ).fetchall():
        explicit = (
            mission_cancelled
            or conn.execute(
                "SELECT 1 FROM events WHERE entity_id=? AND event_type='CASE_CANCELLED'", (case[0],)
            ).fetchone()
        )
        states = [
            row[0]
            for row in conn.execute(
                "SELECT t.status FROM tasks t JOIN case_tasks ct ON ct.task_id=t.id WHERE ct.case_id=?",
                (case[0],),
            )
        ]
        status = "CANCELLED" if case[1] == "CANCELLED" and explicit else "DONE"
        outcome = "CANCELLED" if status == "CANCELLED" else completion_outcome(states)
        conn.execute(
            "UPDATE cases SET status=?,completion_outcome=? WHERE id=?", (status, outcome, case[0])
        )
        conn.execute("UPDATE workstreams SET status=? WHERE id=?", (status, case[2]))
    for stream in conn.execute(
        "SELECT id,status FROM workstreams WHERE status IN ('DONE','CANCELLED')"
    ).fetchall():
        states = [
            row[0]
            for row in conn.execute(
                "SELECT t.status FROM tasks t JOIN task_workstreams tw ON tw.task_id=t.id WHERE tw.workstream_id=?",
                (stream[0],),
            )
        ]
        outcome = "CANCELLED" if stream[1] == "CANCELLED" else completion_outcome(states)
        conn.execute("UPDATE workstreams SET completion_outcome=? WHERE id=?", (outcome, stream[0]))

    # Older dispatchers queued ambiguous attempts for replay. Preserve the job,
    # but require provider reconciliation before any new send under this release.
    rows = conn.execute(
        """SELECT id,mission_id FROM deliveries WHERE status IN ('PENDING','FAILED')
            AND (last_error LIKE 'Delivery lease expired%'
                 OR last_error LIKE 'Extension exited successfully without recording provider acknowledgment%'
                 OR last_error LIKE 'Extension process exited %')"""
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE deliveries SET status='UNKNOWN',claimed_by=NULL,lease_until=NULL WHERE id=?",
            (row[0],),
        )
        conn.execute(
            """INSERT INTO events(id,mission_id,entity_type,entity_id,event_type,actor,occurred_at,payload_json)
                VALUES(?,?,'delivery',?,'DELIVERY_MIGRATED_TO_UNKNOWN','migration',?,?)""",
            (make_id("E"), row[1], row[0], utcnow(), json_dump({"schema_version": 9})),
        )


COORDINATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_references (
    decision_id TEXT NOT NULL REFERENCES decisions(id), task_id TEXT NOT NULL REFERENCES tasks(id),
    actor TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(decision_id,task_id)
);
CREATE INDEX IF NOT EXISTS idx_decision_references_task ON decision_references(task_id);
CREATE TABLE IF NOT EXISTS review_attempts (
    review_id TEXT NOT NULL REFERENCES manager_reviews(id), generation INTEGER NOT NULL,
    agent TEXT NOT NULL UNIQUE, started_at TEXT NOT NULL, ended_at TEXT, disposition TEXT,
    reason TEXT, PRIMARY KEY(review_id,generation)
);
CREATE TABLE IF NOT EXISTS staged_tasks (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id), review_id TEXT NOT NULL REFERENCES manager_reviews(id)
);
CREATE INDEX IF NOT EXISTS idx_staged_review ON staged_tasks(review_id);
CREATE TABLE IF NOT EXISTS acceptance_revisions (
    task_id TEXT NOT NULL REFERENCES tasks(id), revision INTEGER NOT NULL,
    previous_json TEXT NOT NULL, current_json TEXT NOT NULL, actor TEXT NOT NULL,
    reason TEXT NOT NULL, idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(task_id,revision), UNIQUE(task_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS attention_transitions (
    scope TEXT NOT NULL, entity_id TEXT NOT NULL, active INTEGER NOT NULL,
    version INTEGER NOT NULL, since TEXT NOT NULL, PRIMARY KEY(scope,entity_id)
);
CREATE TABLE IF NOT EXISTS decision_aging (
    decision_id TEXT NOT NULL REFERENCES decisions(id), threshold INTEGER NOT NULL,
    PRIMARY KEY(decision_id,threshold)
);
CREATE TABLE IF NOT EXISTS notification_subscriptions (
    id TEXT NOT NULL, version INTEGER NOT NULL, specification_json TEXT NOT NULL,
    cursor INTEGER NOT NULL, active INTEGER NOT NULL, PRIMARY KEY(id,version)
);
CREATE TABLE IF NOT EXISTS notification_deliveries (
    subscription_id TEXT NOT NULL, subscription_version INTEGER NOT NULL, event_seq INTEGER NOT NULL,
    delivery_id TEXT NOT NULL UNIQUE REFERENCES deliveries(id),
    PRIMARY KEY(subscription_id,subscription_version,event_seq)
);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES decisions(id), decision_version INTEGER NOT NULL,
    specification_json TEXT NOT NULL, issued_by TEXT NOT NULL, created_at TEXT NOT NULL,
    revoked_at TEXT, revocation_reason TEXT
);
CREATE TABLE IF NOT EXISTS grant_evaluations (
    id TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES grants(id),
    task_id TEXT NOT NULL REFERENCES tasks(id), generation INTEGER NOT NULL,
    mission_revision INTEGER NOT NULL, acceptance_revision INTEGER NOT NULL,
    condition_id TEXT NOT NULL, revision TEXT NOT NULL, environment TEXT NOT NULL,
    exit_code INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL, expires_at TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_grant_evaluation ON grant_evaluations(grant_id,task_id,condition_id);
CREATE TABLE IF NOT EXISTS grant_waivers (
    id TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES grants(id), condition_id TEXT NOT NULL,
    actor TEXT NOT NULL, reason TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_grant_waiver ON grant_waivers(grant_id,condition_id);
CREATE TABLE IF NOT EXISTS effect_grants (
    effect_id TEXT PRIMARY KEY REFERENCES effects(id), grant_id TEXT NOT NULL REFERENCES grants(id),
    provider TEXT NOT NULL, action TEXT NOT NULL, resource TEXT NOT NULL, environment TEXT NOT NULL
);
"""


def migrate_coordination(conn):
    for name, declaration in (
        ("generation", "INTEGER NOT NULL DEFAULT 0"),
        ("failure_count", "INTEGER NOT NULL DEFAULT 0"),
        ("next_eligible_at", "TEXT"),
        ("last_error", "TEXT"),
    ):
        if name not in {row[1] for row in conn.execute("PRAGMA table_info(manager_reviews)")}:
            conn.execute("ALTER TABLE manager_reviews ADD COLUMN " + name + " " + declaration)
    for table in ("tasks", "attempts", "evidence"):
        if "acceptance_revision" not in {
            row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")
        }:
            conn.execute(
                "ALTER TABLE "
                + table
                + " ADD COLUMN acceptance_revision INTEGER NOT NULL DEFAULT 1"
            )
    execute_schema(conn, COORDINATION_SCHEMA)
    # Running legacy reviews retain their lease and receive an attempt identity.
    conn.execute("UPDATE manager_reviews SET generation=1 WHERE status='RUNNING' AND generation=0")
    conn.execute(
        "INSERT OR IGNORE INTO review_attempts(review_id,generation,agent,started_at) "
        "SELECT id,generation,owner,started_at FROM manager_reviews WHERE status='RUNNING'"
    )
    # A legacy running manager may already have written a partial plan. Do not
    # infer which unclaimed tasks were committed from their timestamps.
    conn.execute(
        "INSERT OR IGNORE INTO staged_tasks(task_id,review_id) "
        "SELECT t.id,r.id FROM tasks t CROSS JOIN manager_reviews r "
        "WHERE r.status='RUNNING' AND t.owner IS NULL AND t.status NOT IN ('DONE','CANCELLED')"
    )


def ensure_schema(conn):
    """Upgrade a known schema under one write transaction; never downgrade."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not row or not row[0].isdigit() or not 1 <= int(row[0]) <= int(SCHEMA_VERSION):
            raise SwarmError("Unsupported schema version; restore with a compatible release")
        for target in range(int(row[0]) + 1, int(SCHEMA_VERSION) + 1):
            # Versions 2–6 introduced additive tables only. Replay their compatible
            # table definitions before the version 7 runtime migration.
            if target == 13:
                migrate_coordination(conn)
            elif target == 12:
                execute_schema(conn, EVIDENCE_SCHEMA)
            elif target == 11:
                migrate_review_batches(conn)
            elif target == 10:
                execute_schema(conn, WORKSPACE_CREATION_SCHEMA)
            elif target == 9:
                migrate_reliability_schema(conn)
            elif target == 8:
                migrate_workspace_schema(conn)
            else:
                execute_schema(conn, SCHEMA if target <= 6 else RUNTIME_SCHEMA)
            conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(target),))
        conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('mission_mode','FINITE')")
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('swarmctl_version',?)", (VERSION,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
