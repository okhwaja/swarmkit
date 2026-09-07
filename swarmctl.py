#!/usr/bin/env python3
"""Swarmkit CLI and compatibility imports for existing Python adapters.

New integrations should import the owning swarmkit module directly.
"""

from swarmkit.audit import audit_summary, verify_audit, export_audit
from swarmkit.cases import (
    snapshot_case_payload,
    link_case_task,
    open_case,
    apply_policy_to_case,
    wake_case_from_signal,
    add_case_signal,
    cancel_case,
)
from swarmkit.cli import add_runtime_cli, handle_runtime_cli, parser, main
from swarmkit.config import runner_config
from swarmkit.coordination import (
    reconcile_deliveries,
    request_manager_review,
    reconcile_manager_reviews,
    claim_manager_review,
    finish_manager_review,
    raise_finding,
    dispose_finding,
    start_external_wait,
    _wake_external_wait,
    signal_external_wait,
    reconcile_external_waits,
    reconcile_conn,
    reconcile_cases,
    commit_review,
)
from swarmkit.core import (
    VERSION,
    SCHEMA_VERSION,
    ACTIVE_TASK_STATES,
    TERMINAL_TASK_STATES,
    VALID_TASK_STATES,
    VALID_TASK_KINDS,
    VALID_WORKSTREAM_STATES,
    VALID_FORECAST_CONFIDENCE,
    VALID_BLOCKER_KINDS,
    VALID_DELIVERY_STATES,
    VALID_CASE_STATES,
    VALID_MISSION_MODES,
    VALID_FINDING_SIGNIFICANCE,
    VALID_FINDING_STATES,
    VALID_WAIT_STATES,
    VALID_WAKE_REASONS,
    VALID_MANAGER_REVIEW_STATES,
    SwarmError,
    transaction,
    atomic_write,
    utcnow,
    parse_time,
    canonical_time,
    make_id,
    json_dump,
    json_load,
    root_path,
    db_path,
    delivery_content_intact,
    hash_file,
    case_payload_intact,
    print_json,
    future_time,
    process_lock,
)
from swarmkit.decisions import (
    validate_decision_choice,
    require_decision_choice,
    resolve_decision,
    revise_decision,
    link_decision,
    acknowledge_decision,
)
from swarmkit.delivery import (
    validate_extension_manifest,
    read_extension_source,
    install_extension,
    validate_recipients,
    parse_metadata,
    enqueue_delivery,
    claim_delivery,
    mark_delivery_sent,
    mark_delivery_failed,
    retry_delivery,
    cancel_delivery,
    write_delivery_envelope,
    write_delivery_prompt,
    prepare_delivery_command,
    dispatch_delivery,
)
from swarmkit.diagnostics import doctor
from swarmkit.effects import (
    prepare_effect,
    transition_effect,
    acquire_resource,
    release_resource,
)
from swarmkit.evidence import set_contract, record_evidence, evidence_gaps
from swarmkit.inbox import inbox, lease_inbox, ack_inbox
from swarmkit.policies import (
    validate_policy_manifest,
    read_policy_source,
    install_policy,
    parse_policy_variables,
    render_policy_text,
    apply_policy,
)
from swarmkit.prompts import guidance_path, role_for_task, build_prompt, write_prompt
from swarmkit.queries import (
    policy_pack_dict,
    policy_pack_summary,
    policy_application_dict,
    policy_context_for_task,
    extension_dict,
    extension_summary,
    delivery_dict,
    manager_review_dict,
    finding_dict,
    external_wait_dict,
    signal_dict,
    case_dict,
    case_summary,
    task_dict,
    decision_dict,
    workstream_dict,
    mission_snapshot,
    explain_state,
    workspace_dict,
)
from swarmkit.runtime import (
    dispatch,
    external_wait_summary,
    run_loop,
    _run_loop,
    recover_runs,
    abandon_run,
    serve,
)
from swarmkit.schema import (
    SCHEMA,
    RUNTIME_SCHEMA,
    execute_schema,
    migrate_workspace_schema,
    ensure_schema,
)
from swarmkit.setup import initialize, setup_check
from swarmkit.storage import (
    connect,
    mission,
    mission_mode,
    add_event,
    task_row,
    decision_row,
    workstream_row,
    require_delivery_owner,
    all_dependencies_done,
    open_decision_count,
    unresolved_ack_count,
    finding_row,
    external_wait_row,
    require_owner,
    case_row,
    register_artifact,
    runtime_state,
    require_active_mission,
    attempt_for_task,
    end_attempt,
    uncertain_effects,
    require_task_capacity,
    budget_reason,
)
from swarmkit.tasks import (
    add_workstream,
    update_workstream,
    link_task_workstream,
    verify_dependencies_exist,
    add_task,
    approve_task,
    claim_task,
    checkpoint_task,
    complete_task,
    cancel_task,
    block_task,
    record_fact,
    set_mission_phase,
    complete_mission,
    control_mission,
    configure_runtime,
    amend_mission,
)
from swarmkit.views import (
    md_escape,
    forecast_text,
    render_board,
    render_status_report,
)
from swarmkit.workspaces import (
    workspace_config,
    workspace_task,
    register_workspace,
    run_workspace_command,
    create_workspace,
)

if __name__ == "__main__":
    raise SystemExit(main())
