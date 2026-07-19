"""Authoritative policy classification for unsafe-method Harness UI routes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from gpt2giga_harness.runtime.policy import (
    MCP_SERVER_PROBE_OWNER,
    NATIVE_PROCESS_SPAWN_OWNER,
    REVIEWED_PROMOTION_APPLY_OWNER,
    REVIEWED_PROMOTION_BRANCH_OWNER,
    REVIEWED_PROMOTION_MERGE_OWNER,
    SCHEDULE_CREATE_OWNER,
    SCHEDULE_ENABLE_OWNER,
    SCHEDULE_RUN_NOW_OWNER,
    PermissionAction,
)

UNSAFE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class MutationClass(str, Enum):
    """Semantic effect of an unsafe-method route."""

    READ_ONLY = "read_only"
    LOCAL_STATE = "local_state_mutation"
    GOVERNED_EXTERNAL_EFFECT = "governed_external_effect"
    REVIEWED_PROMOTION = "reviewed_promotion"


class EnforcementControl(str, Enum):
    """Existing component that prevents an unsafe route from bypassing policy."""

    AUTHENTICATED_PROJECTION = "authenticated_projection"
    AUTHENTICATED_LOCAL_STATE = "authenticated_local_state"
    OPTIMISTIC_LOCAL_STATE = "optimistic_local_state"
    EXPLICIT_OPERATOR_ACTION = "explicit_operator_action"
    SELECTED_PLAN_PREFLIGHT = "selected_plan_preflight"
    POLICY_ENGINE = "policy_engine"
    REVIEW_BINDING = "review_binding"
    BOOTSTRAP_AUTH = "bootstrap_auth"


class ConformanceBehavior(str, Enum):
    """Machine-readable behavior exercised by retained conformance evidence."""

    AUTHENTICATION = "authentication"
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    STALE_OR_REBOUND = "stale_or_rebound"
    REDACTION = "redaction"


@dataclass(frozen=True)
class ConformanceEvidence:
    """Retained test evidence shared by one or more route contracts."""

    id: str
    behaviors: frozenset[ConformanceBehavior]
    test_nodes: tuple[str, ...]


@dataclass(frozen=True)
class MutationRouteContract:
    """One exact unsafe-method route and its real enforcement contract."""

    method: str
    path: str
    mutation_class: MutationClass
    control: EnforcementControl
    enforcement_owner: str | None
    permission_actions: tuple[PermissionAction, ...]
    evidence_ids: tuple[str, ...]

    @property
    def identity(self) -> tuple[str, str]:
        """Return the exact HTTP method and normalized FastAPI path."""
        return self.method, self.path


CONFORMANCE_EVIDENCE = {
    item.id: item
    for item in (
        ConformanceEvidence(
            id="ui.auth_boundary",
            behaviors=frozenset(
                {ConformanceBehavior.AUTHENTICATION, ConformanceBehavior.DENY}
            ),
            test_nodes=(
                "tests/harness/test_ui_security.py::test_remote_mutations_fail_closed_without_auth_configuration",
            ),
        ),
        ConformanceEvidence(
            id="ui.redaction_boundary",
            behaviors=frozenset({ConformanceBehavior.REDACTION}),
            test_nodes=(
                "tests/harness/test_ui_security.py::test_ui_security_config_loads_token_and_host_allowlist_without_api_exposure",
            ),
        ),
        ConformanceEvidence(
            id="projection.allow",
            behaviors=frozenset({ConformanceBehavior.ALLOW}),
            test_nodes=(
                "tests/harness/test_project_api.py::test_project_presets_api_lists_and_renders_presets",
            ),
        ),
        ConformanceEvidence(
            id="local_state.allow",
            behaviors=frozenset(
                {ConformanceBehavior.ALLOW, ConformanceBehavior.REDACTION}
            ),
            test_nodes=(
                "tests/harness/test_project_api.py::test_project_memory_api_crud_redacts_and_filters",
                "tests/harness/test_attachments_api.py::test_attachments_api_rejects_unsafe_upload_without_leaking_payload",
            ),
        ),
        ConformanceEvidence(
            id="local_state.optimistic",
            behaviors=frozenset(
                {
                    ConformanceBehavior.ALLOW,
                    ConformanceBehavior.DENY,
                    ConformanceBehavior.STALE_OR_REBOUND,
                    ConformanceBehavior.REDACTION,
                }
            ),
            test_nodes=(
                "tests/harness/test_agents_api.py::test_agent_api_detects_etag_conflict_and_rejects_bad_profile",
                "tests/harness/test_workflows_api.py::test_workflow_catalog_api_edits_histories_duplicates_imports_and_exports",
                "tests/harness/test_managed_mcp.py::test_managed_service_rejects_active_home_stale_preview_and_external_edit",
            ),
        ),
        ConformanceEvidence(
            id="provider.settings",
            behaviors=frozenset(
                {
                    ConformanceBehavior.AUTHENTICATION,
                    ConformanceBehavior.ALLOW,
                    ConformanceBehavior.DENY,
                    ConformanceBehavior.STALE_OR_REBOUND,
                    ConformanceBehavior.REDACTION,
                }
            ),
            test_nodes=(
                "tests/harness/test_settings_api.py::test_provider_settings_api_crud_is_reference_only_and_optimistic",
                "tests/harness/test_settings_api.py::test_provider_settings_api_returns_field_errors_before_persistence",
                "tests/harness/test_settings_api.py::test_provider_settings_api_probe_is_explicit_bounded_and_content_free",
            ),
        ),
        ConformanceEvidence(
            id="external.editor",
            behaviors=frozenset(
                {
                    ConformanceBehavior.ALLOW,
                    ConformanceBehavior.DENY,
                    ConformanceBehavior.REDACTION,
                }
            ),
            test_nodes=(
                "tests/harness/test_editor_api.py::test_editor_open_file_api_builds_dry_run_command",
                "tests/harness/test_editor_api.py::test_editor_open_file_api_rejects_path_escape",
            ),
        ),
        ConformanceEvidence(
            id="external.selected_plan",
            behaviors=frozenset(
                {
                    ConformanceBehavior.ALLOW,
                    ConformanceBehavior.DENY,
                    ConformanceBehavior.REDACTION,
                }
            ),
            test_nodes=(
                "tests/harness/test_ui.py::test_ui_can_run_echo_harness",
                "tests/harness/test_ui.py::test_ui_run_blocks_private_key_prompt_without_echoing_secret",
            ),
        ),
        ConformanceEvidence(
            id="external.native_control",
            behaviors=frozenset(
                {
                    ConformanceBehavior.ALLOW,
                    ConformanceBehavior.DENY,
                    ConformanceBehavior.REDACTION,
                }
            ),
            test_nodes=(
                "tests/harness/test_native_process_api.py::test_native_process_api_start_poll_input_and_stop",
                "tests/harness/test_native_process_api.py::test_native_process_resize_api_validates_terminal_limits",
            ),
        ),
        ConformanceEvidence(
            id="policy.lifecycle",
            behaviors=frozenset(ConformanceBehavior),
            test_nodes=(
                "tests/harness/test_policy_approvals.py::test_approval_allow_once_requeues_pre_spawn_job_and_is_consumed",
                "tests/harness/test_policy_approvals.py::test_denied_pre_spawn_approval_cancels_without_attempt",
                "tests/harness/test_policy_approvals.py::test_hash_bound_approval_cannot_be_broadened_or_rebound",
                "tests/harness/test_native_process_api.py::test_native_process_api_redacts_start_output_and_events",
            ),
        ),
        ConformanceEvidence(
            id="policy.native_process",
            behaviors=frozenset({ConformanceBehavior.ALLOW, ConformanceBehavior.ASK}),
            test_nodes=(
                "tests/harness/test_native_process_api.py::test_native_process_api_approval_blocks_before_worktree_and_spawn",
                "tests/harness/test_native_process_api.py::test_native_process_api_edit_uses_approved_isolated_worktree",
            ),
        ),
        ConformanceEvidence(
            id="policy.mcp_probe",
            behaviors=frozenset({ConformanceBehavior.ALLOW, ConformanceBehavior.ASK}),
            test_nodes=(
                "tests/harness/test_mcp.py::test_tools_api_lists_compatibility_and_policy_gates_untrusted_probe",
                "tests/harness/test_mcp.py::test_missing_secret_blocks_probe_without_leaking_reference_value",
            ),
        ),
        ConformanceEvidence(
            id="policy.schedule",
            behaviors=frozenset({ConformanceBehavior.ALLOW, ConformanceBehavior.ASK}),
            test_nodes=(
                "tests/harness/test_schedules.py::test_schedule_api_requires_exact_test_hash_and_online_worker",
            ),
        ),
        ConformanceEvidence(
            id="reviewed.git",
            behaviors=frozenset(ConformanceBehavior),
            test_nodes=(
                "tests/harness/test_ui_sessions_api.py::test_runs_api_diff_apply_and_open_worktree",
                "tests/harness/test_ui_sessions_api.py::test_runs_api_pr_artifact_patch_and_branch_creation",
                "tests/harness/test_policy_approvals.py::test_reviewed_promotion_denial_has_no_enforcement_event",
            ),
        ),
        ConformanceEvidence(
            id="reviewed.project_artifact",
            behaviors=frozenset(
                {
                    ConformanceBehavior.ALLOW,
                    ConformanceBehavior.ASK,
                    ConformanceBehavior.DENY,
                    ConformanceBehavior.STALE_OR_REBOUND,
                    ConformanceBehavior.REDACTION,
                }
            ),
            test_nodes=(
                "tests/harness/test_promotions.py::test_run_promotion_requires_review_and_writes_each_project_yaml",
                "tests/harness/test_promotions.py::test_run_promotion_rejects_unreviewed_edits_and_stale_target",
            ),
        ),
        ConformanceEvidence(
            id="integrations.flow",
            behaviors=frozenset(ConformanceBehavior),
            test_nodes=(
                "tests/harness/test_integrations_api.py::test_integration_api_keeps_preview_apply_progress_and_rollback_equivalent",
                "tests/harness/test_integrations_api.py::test_integration_api_validates_fields_and_never_returns_secret_payloads",
                "tests/harness/test_integration_flows.py::test_flow_rejects_secret_values_stale_approval_and_records_failure",
            ),
        ),
        ConformanceEvidence(
            id="auth.bootstrap",
            behaviors=frozenset(
                {
                    ConformanceBehavior.AUTHENTICATION,
                    ConformanceBehavior.ALLOW,
                    ConformanceBehavior.DENY,
                    ConformanceBehavior.REDACTION,
                }
            ),
            test_nodes=(
                "tests/harness/test_ui_security.py::test_remote_shell_requires_bootstrap_exchange_for_api_and_sse_cookie",
            ),
        ),
    )
}

_AUTH = ("ui.auth_boundary", "ui.redaction_boundary")
_READ = (*_AUTH, "projection.allow")
_LOCAL = (*_AUTH, "local_state.allow")
_OPTIMISTIC = (*_AUTH, "local_state.optimistic")
_EXTERNAL = (*_AUTH, "external.selected_plan")
_EDITOR = (*_AUTH, "external.editor")
_NATIVE_CONTROL = (*_AUTH, "external.native_control")
_POLICY = (*_AUTH, "policy.lifecycle")
_PROVIDER_SETTINGS = (*_AUTH, "provider.settings")
_INTEGRATION_FLOW = (*_AUTH, "integrations.flow")


def _route(
    method: str,
    path: str,
    mutation_class: MutationClass,
    control: EnforcementControl,
    owner: str | None,
    *,
    actions: tuple[PermissionAction, ...] = (),
    evidence: tuple[str, ...],
) -> MutationRouteContract:
    return MutationRouteContract(
        method=method,
        path=path,
        mutation_class=mutation_class,
        control=control,
        enforcement_owner=owner,
        permission_actions=actions,
        evidence_ids=evidence,
    )


def _many(
    method: str,
    paths: Iterable[str],
    mutation_class: MutationClass,
    control: EnforcementControl,
    owner: str | None,
    *,
    actions: tuple[PermissionAction, ...] = (),
    evidence: tuple[str, ...],
) -> tuple[MutationRouteContract, ...]:
    return tuple(
        _route(
            method,
            path,
            mutation_class,
            control,
            owner,
            actions=actions,
            evidence=evidence,
        )
        for path in paths
    )


MUTATION_ROUTE_CONTRACTS = (
    *_many(
        "POST",
        (
            "/api/project/presets/{preset_name}/render",
            "/api/tools/sync",
            "/api/preflight/run",
            "/api/route/recommendation",
            "/api/agents/validate",
            "/api/agents/{agent_id}/draft",
            "/api/agents/{agent_id}/duplicate",
            "/api/tool-config/preview",
            "/api/runs/{run_id}/promotions/preview",
            "/api/workflows/validate",
            "/api/schedules/preview",
        ),
        MutationClass.READ_ONLY,
        EnforcementControl.AUTHENTICATED_PROJECTION,
        None,
        evidence=_READ,
    ),
    *_many(
        "PATCH",
        (
            "/api/project/state",
            "/api/project/memory/{memory_id}",
            "/api/settings/defaults",
            "/api/sessions/{session_id}",
        ),
        MutationClass.LOCAL_STATE,
        EnforcementControl.AUTHENTICATED_LOCAL_STATE,
        "local_state.patch",
        evidence=_LOCAL,
    ),
    _route(
        "POST",
        "/api/providers",
        MutationClass.LOCAL_STATE,
        EnforcementControl.OPTIMISTIC_LOCAL_STATE,
        "provider_settings.create",
        evidence=_PROVIDER_SETTINGS,
    ),
    _route(
        "PATCH",
        "/api/providers/{provider_id}",
        MutationClass.LOCAL_STATE,
        EnforcementControl.OPTIMISTIC_LOCAL_STATE,
        "provider_settings.update",
        evidence=_PROVIDER_SETTINGS,
    ),
    *_many(
        "DELETE",
        (
            "/api/project/memory/{memory_id}",
            "/api/sessions/{session_id}",
            "/api/attachments/{attachment_id}",
            "/api/schedules/{schedule_id}",
        ),
        MutationClass.LOCAL_STATE,
        EnforcementControl.AUTHENTICATED_LOCAL_STATE,
        "local_state.delete",
        evidence=_LOCAL,
    ),
    *_many(
        "POST",
        (
            "/api/project/memory",
            "/api/project/init",
            "/api/sessions",
            "/api/native/sessions/sync",
            "/api/native/sessions/{native_ref_id}/import",
            "/api/sessions/{session_id}/native/link",
            "/api/sessions/{session_id}/attachments",
            "/api/sessions/{session_id}/attachments/workspace",
            "/api/runs/{run_id}/cancel",
            "/api/runs/{run_id}/discard",
            "/api/attention/read",
            "/api/approvals/{approval_id}/decision",
            "/api/evaluate/runs/{eval_run_id}/baseline",
            "/api/evaluate/runs/{eval_run_id}/cancel",
            "/api/workflow-runs/{run_id}/cancel",
            "/api/workflow-runs/{run_id}/handoffs/{step_id}/choose",
            "/api/workflow-runs/{run_id}/handoffs/{step_id}/discard",
            "/api/workflow-runs/{run_id}/merge-queue",
            "/api/runs/{run_id}/retry",
            "/api/schedules/{schedule_id}/pause",
        ),
        MutationClass.LOCAL_STATE,
        EnforcementControl.AUTHENTICATED_LOCAL_STATE,
        "local_state.control_plane",
        evidence=_LOCAL,
    ),
    *_many(
        "POST",
        (
            "/api/agents/{agent_id}/apply",
            "/api/tool-config/apply",
            "/api/tool-config/rollback",
            "/api/workflows/import",
            "/api/workflows/{workflow_id}/duplicate",
        ),
        MutationClass.LOCAL_STATE,
        EnforcementControl.OPTIMISTIC_LOCAL_STATE,
        "project_authoring.optimistic_apply",
        evidence=_OPTIMISTIC,
    ),
    _route(
        "PUT",
        "/api/workflows/{workflow_id}",
        MutationClass.LOCAL_STATE,
        EnforcementControl.OPTIMISTIC_LOCAL_STATE,
        "workflow_catalog.save",
        evidence=_OPTIMISTIC,
    ),
    _route(
        "POST",
        "/api/integrations/preview",
        MutationClass.LOCAL_STATE,
        EnforcementControl.OPTIMISTIC_LOCAL_STATE,
        "integration_flow.preview",
        evidence=_INTEGRATION_FLOW,
    ),
    *_many(
        "POST",
        (
            "/api/integrations/flows/{flow_id}/apply",
            "/api/integrations/flows/{flow_id}/rollback",
        ),
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.REVIEW_BINDING,
        "integration_flow.exact_plan",
        evidence=_INTEGRATION_FLOW,
    ),
    *_many(
        "POST",
        (
            "/api/editor/open-workspace",
            "/api/editor/open-file",
            "/api/editor/open-diff",
            "/api/editor/open-terminal",
            "/api/runs/{run_id}/open-worktree",
        ),
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.EXPLICIT_OPERATOR_ACTION,
        "editor.execute_plan",
        actions=(PermissionAction.PROCESS_SPAWN,),
        evidence=_EDITOR,
    ),
    *_many(
        "POST",
        (
            "/api/evals/{eval_name}/runs",
            "/api/sessions/run/start",
            "/api/sessions/{session_id}/run/start",
            "/api/runs/{run_id}/replay",
            "/api/runs/{run_id}/fork",
            "/api/sessions/run",
            "/api/sessions/{session_id}/run",
            "/api/arena/runs",
            "/api/arena/runs/{arena_id}/turns",
            "/api/arena/runs/{arena_id}/children/{child_index}/retry",
            "/api/run",
            "/api/agents/{agent_id}/run",
            "/api/workflows/{workflow_id}/run",
            "/api/schedules/{schedule_id}/test-now",
        ),
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.SELECTED_PLAN_PREFLIGHT,
        "execution.selected_plan",
        actions=(PermissionAction.PROCESS_SPAWN,),
        evidence=_EXTERNAL,
    ),
    *_many(
        "POST",
        (
            "/api/native/processes/{process_id}/input",
            "/api/native/processes/{process_id}/resize",
        ),
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.EXPLICIT_OPERATOR_ACTION,
        "native_process.control",
        evidence=_NATIVE_CONTROL,
    ),
    *_many(
        "POST",
        (
            "/api/providers/{provider_id}/test",
            "/api/providers/{provider_id}/discover",
        ),
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.EXPLICIT_OPERATOR_ACTION,
        "provider_settings.probe",
        actions=(PermissionAction.NETWORK_CONNECT,),
        evidence=_PROVIDER_SETTINGS,
    ),
    _route(
        "DELETE",
        "/api/native/processes/{process_id}",
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.EXPLICIT_OPERATOR_ACTION,
        "native_process.stop",
        evidence=_NATIVE_CONTROL,
    ),
    _route(
        "POST",
        "/api/native/processes/start",
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.POLICY_ENGINE,
        NATIVE_PROCESS_SPAWN_OWNER,
        actions=(PermissionAction.PROCESS_SPAWN,),
        evidence=(*_POLICY, "policy.native_process"),
    ),
    _route(
        "POST",
        "/api/tool-servers/{server_id}/probe",
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.POLICY_ENGINE,
        MCP_SERVER_PROBE_OWNER,
        actions=(PermissionAction.MCP_SERVER_START, PermissionAction.NETWORK_CONNECT),
        evidence=(*_POLICY, "policy.mcp_probe"),
    ),
    *_many(
        "POST",
        ("/api/schedules",),
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.POLICY_ENGINE,
        SCHEDULE_CREATE_OWNER,
        actions=(PermissionAction.SCHEDULE_CREATE,),
        evidence=(*_POLICY, "policy.schedule"),
    ),
    _route(
        "PUT",
        "/api/schedules/{schedule_id}",
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.POLICY_ENGINE,
        SCHEDULE_CREATE_OWNER,
        actions=(PermissionAction.SCHEDULE_CREATE,),
        evidence=(*_POLICY, "policy.schedule"),
    ),
    *_many(
        "POST",
        (
            "/api/schedules/{schedule_id}/enable",
            "/api/schedules/{schedule_id}/resume",
        ),
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.POLICY_ENGINE,
        SCHEDULE_ENABLE_OWNER,
        actions=(PermissionAction.SCHEDULE_ENABLE,),
        evidence=(*_POLICY, "policy.schedule"),
    ),
    _route(
        "POST",
        "/api/schedules/{schedule_id}/run-now",
        MutationClass.GOVERNED_EXTERNAL_EFFECT,
        EnforcementControl.POLICY_ENGINE,
        SCHEDULE_RUN_NOW_OWNER,
        actions=(PermissionAction.SCHEDULE_RUN_NOW,),
        evidence=(*_POLICY, "policy.schedule"),
    ),
    _route(
        "POST",
        "/api/runs/{run_id}/apply",
        MutationClass.REVIEWED_PROMOTION,
        EnforcementControl.REVIEW_BINDING,
        REVIEWED_PROMOTION_APPLY_OWNER,
        actions=(PermissionAction.GIT_APPLY,),
        evidence=(*_AUTH, "reviewed.git"),
    ),
    _route(
        "POST",
        "/api/runs/{run_id}/branch",
        MutationClass.REVIEWED_PROMOTION,
        EnforcementControl.REVIEW_BINDING,
        REVIEWED_PROMOTION_BRANCH_OWNER,
        actions=(PermissionAction.GIT_BRANCH_CREATE,),
        evidence=(*_AUTH, "reviewed.git"),
    ),
    _route(
        "POST",
        "/api/workflow-runs/{run_id}/merge-queue/apply",
        MutationClass.REVIEWED_PROMOTION,
        EnforcementControl.REVIEW_BINDING,
        REVIEWED_PROMOTION_MERGE_OWNER,
        actions=(PermissionAction.GIT_APPLY,),
        evidence=(*_AUTH, "reviewed.git"),
    ),
    _route(
        "POST",
        "/api/runs/{run_id}/promotions/apply",
        MutationClass.REVIEWED_PROMOTION,
        EnforcementControl.REVIEW_BINDING,
        "reviewed_promotion.project_artifact_apply",
        evidence=(*_AUTH, "reviewed.project_artifact"),
    ),
    _route(
        "POST",
        "/auth/session",
        MutationClass.LOCAL_STATE,
        EnforcementControl.BOOTSTRAP_AUTH,
        "ui_security.browser_session",
        evidence=("auth.bootstrap",),
    ),
)


def required_behaviors(
    contract: MutationRouteContract,
) -> frozenset[ConformanceBehavior]:
    """Return the minimum behavior set required for a declared control."""
    behaviors = {
        ConformanceBehavior.AUTHENTICATION,
        ConformanceBehavior.ALLOW,
        ConformanceBehavior.DENY,
        ConformanceBehavior.REDACTION,
    }
    if contract.control is EnforcementControl.POLICY_ENGINE:
        behaviors.update(
            {ConformanceBehavior.ASK, ConformanceBehavior.STALE_OR_REBOUND}
        )
    if contract.control in {
        EnforcementControl.OPTIMISTIC_LOCAL_STATE,
        EnforcementControl.REVIEW_BINDING,
    }:
        behaviors.add(ConformanceBehavior.STALE_OR_REBOUND)
    if contract.control is EnforcementControl.REVIEW_BINDING:
        behaviors.add(ConformanceBehavior.ASK)
    return frozenset(behaviors)


def declared_behaviors(
    contract: MutationRouteContract,
) -> frozenset[ConformanceBehavior]:
    """Return the union of retained behavior evidence declared for one route."""
    behaviors: set[ConformanceBehavior] = set()
    for evidence_id in contract.evidence_ids:
        evidence = CONFORMANCE_EVIDENCE.get(evidence_id)
        if evidence is not None:
            behaviors.update(evidence.behaviors)
    return frozenset(behaviors)


def unsafe_route_identities(routes: Sequence[object]) -> frozenset[tuple[str, str]]:
    """Recursively expand included FastAPI routers into unsafe route identities."""
    identities: set[tuple[str, str]] = set()
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            identities.update(unsafe_route_identities(included.routes))
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or ()
        if not isinstance(path, str):
            continue
        identities.update(
            (method, path) for method in methods if method in UNSAFE_HTTP_METHODS
        )
    return frozenset(identities)


def mutation_contract_errors(routes: Sequence[object]) -> tuple[str, ...]:
    """Return deterministic errors for route, owner, action, or evidence drift."""
    errors: list[str] = []
    identities = [contract.identity for contract in MUTATION_ROUTE_CONTRACTS]
    duplicates = sorted(
        identity for identity in set(identities) if identities.count(identity) > 1
    )
    if duplicates:
        errors.append(f"duplicate mutation contracts: {duplicates}")
    runtime = unsafe_route_identities(routes)
    declared = frozenset(identities)
    missing = sorted(runtime - declared)
    stale = sorted(declared - runtime)
    if missing:
        errors.append(f"unclassified unsafe routes: {missing}")
    if stale:
        errors.append(f"contracts without routes: {stale}")
    for contract in MUTATION_ROUTE_CONTRACTS:
        label = f"{contract.method} {contract.path}"
        unknown_evidence = sorted(
            set(contract.evidence_ids) - CONFORMANCE_EVIDENCE.keys()
        )
        if unknown_evidence:
            errors.append(f"{label} has unknown evidence: {unknown_evidence}")
        if (
            contract.mutation_class is MutationClass.READ_ONLY
            and contract.enforcement_owner is not None
        ):
            errors.append(f"{label} read-only route must not declare a mutation owner")
        if (
            contract.mutation_class is not MutationClass.READ_ONLY
            and not contract.enforcement_owner
        ):
            errors.append(f"{label} mutation route has no enforcement owner")
        if contract.control is EnforcementControl.POLICY_ENGINE and (
            not contract.permission_actions or not contract.enforcement_owner
        ):
            errors.append(f"{label} policy-engine route lacks action or owner")
        missing_behaviors = sorted(
            behavior.value
            for behavior in required_behaviors(contract) - declared_behaviors(contract)
        )
        if missing_behaviors:
            errors.append(f"{label} lacks conformance evidence: {missing_behaviors}")
    return tuple(errors)


def install_mutation_contracts(app: object) -> None:
    """Fail closed on route drift and expose the validated inventory on app state."""
    routes = getattr(app, "routes")
    errors = mutation_contract_errors(routes)
    if errors:
        raise RuntimeError("Harness mutation contract invalid: " + "; ".join(errors))
    getattr(app, "state").harness_mutation_contracts = MUTATION_ROUTE_CONTRACTS
