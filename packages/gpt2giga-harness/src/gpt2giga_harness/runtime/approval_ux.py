"""Fail-closed Approval Center projections for governed actions."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping

from gpt2giga_harness.runtime.policy import (
    ApprovalDecision,
    ApprovalRequest,
    PermissionAction,
    approval_binding_digest,
    redacted_policy_preview,
)


APPROVAL_UX_SCHEMA_VERSION = 1
_PROTECTED_ACTIONS = frozenset(
    {
        PermissionAction.EXTERNAL_WRITE,
        PermissionAction.SCHEDULE_UNATTENDED_EDIT,
    }
)
_PERSISTABLE_ACTIONS = frozenset({PermissionAction.WORKSPACE_READ})
_PROTECTED_PATH_PARTS = frozenset(
    {
        ".env",
        ".git",
        ".ssh",
        ".gnupg",
        ".aws",
        ".config",
    }
)
_HIGH_RISK_ACTIONS = frozenset(
    {
        PermissionAction.GIT_PUSH,
        PermissionAction.GITHUB_PULL_REQUEST_CREATE,
        PermissionAction.EXTERNAL_WRITE,
        PermissionAction.SCHEDULE_UNATTENDED_EDIT,
    }
)
_MEDIUM_RISK_ACTIONS = frozenset(
    {
        PermissionAction.WORKSPACE_WRITE,
        PermissionAction.PROCESS_SPAWN,
        PermissionAction.NETWORK_CONNECT,
        PermissionAction.MCP_SERVER_START,
        PermissionAction.MCP_TOOL_CALL,
        PermissionAction.GIT_COMMIT,
        PermissionAction.GIT_APPLY,
        PermissionAction.GIT_BRANCH_CREATE,
        PermissionAction.SCHEDULE_CREATE,
        PermissionAction.SCHEDULE_ENABLE,
        PermissionAction.SCHEDULE_RUN_NOW,
    }
)


def approval_ux_projection(request: ApprovalRequest) -> dict[str, Any]:
    """Project one request into bounded, explainable Approval Center fields."""
    preview = redacted_policy_preview(request.preview)
    preview_sha256 = _json_hash(preview)
    binding = _preview_binding(preview)
    protected_reason = _protected_reason(request.action, preview)
    target = _target_projection(request.action, preview)
    options = _decision_options(
        request,
        preview_bound=binding is not None,
        protected=protected_reason is not None,
    )
    risk = _risk(request.action, protected=protected_reason is not None)
    return {
        "schema_version": APPROVAL_UX_SCHEMA_VERSION,
        "action": request.action.value,
        "target": target,
        "scope": {
            "operation_id": request.job_id or request.id,
            "session_id": request.session_id,
            "project_id": request.project_id,
        },
        "duration": "pending_operator_choice",
        "policy_source": request.policy_source,
        "enforcement": request.enforcement.value,
        "risk": risk,
        "preview_sha256": preview_sha256,
        "preview_bound": binding is not None,
        "consequence": _consequence(request.action),
        "why": _why(request, protected_reason=protected_reason),
        "what_changed": (
            "exact_preview_bound"
            if binding is not None
            else "preview_digest_available_for_comparison"
        ),
        "protected": protected_reason is not None,
        "protected_reason": protected_reason,
        "decision_options": options,
        "side_effect_free": True,
        "grant_created": False,
    }


def _decision_options(
    request: ApprovalRequest,
    *,
    preview_bound: bool,
    protected: bool,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = [
        {
            "decision": ApprovalDecision.DENY.value,
            "lifetime": "operation",
            "enabled": True,
            "expires_in_seconds": None,
            "why": "deny_is_always_available",
        }
    ]
    if protected:
        return options
    options.append(
        {
            "decision": ApprovalDecision.ALLOW_ONCE.value,
            "lifetime": "operation",
            "enabled": True,
            "expires_in_seconds": None,
            "why": "exact_operation_only",
        }
    )
    options.append(
        {
            "decision": ApprovalDecision.ALLOW_SESSION.value,
            "lifetime": "session",
            "enabled": request.session_id is not None and not preview_bound,
            "expires_in_seconds": None,
            "why": (
                "session_scope_available"
                if request.session_id is not None and not preview_bound
                else "session_scope_requires_unbound_session_request"
            ),
        }
    )
    persistent_enabled = (
        request.project_id is not None
        and not preview_bound
        and request.action in _PERSISTABLE_ACTIONS
    )
    options.append(
        {
            "decision": ApprovalDecision.ALLOW_PROJECT.value,
            "lifetime": "persisted_policy",
            "enabled": persistent_enabled,
            "expires_in_seconds": 3600,
            "why": (
                "reviewed_persisted_policy_available"
                if persistent_enabled
                else "persistent_scope_not_permitted_for_this_action"
            ),
        }
    )
    return options


def _target_projection(
    action: PermissionAction,
    preview: Mapping[str, Any],
) -> dict[str, Any]:
    repository = preview.get("repository")
    repository_value = (
        repository.get("name_with_owner")
        if isinstance(repository, Mapping)
        else repository
    )
    candidates = {
        "repository": repository_value,
        "remote": preview.get("remote"),
        "target_branch": preview.get("target_branch"),
        "host": preview.get("host"),
        "port": preview.get("port"),
        "protocol": preview.get("protocol"),
        "method": preview.get("method"),
        "method_class": preview.get("method_class"),
        "redirect_policy": preview.get("redirect_policy"),
        "purpose": preview.get("purpose"),
        "max_request_body_bytes": preview.get("max_request_body_bytes"),
        "max_response_body_bytes": preview.get("max_response_body_bytes"),
        "server_id": preview.get("server_id"),
        "transport": preview.get("transport"),
        "harness_id": preview.get("harness_id"),
        "url": preview.get("url"),
        "command": preview.get("command"),
        "path": preview.get("path"),
        "relative_path": preview.get("relative_path"),
        "workspace": preview.get("workspace"),
        "operation": preview.get("operation"),
    }
    return {
        "kind": _target_kind(action),
        "fields": {
            key: value
            for key, value in candidates.items()
            if isinstance(value, (str, int, float, bool)) and str(value)
        },
    }


def _target_kind(action: PermissionAction) -> str:
    if action in {PermissionAction.WORKSPACE_READ, PermissionAction.WORKSPACE_WRITE}:
        return "filesystem"
    if action is PermissionAction.PROCESS_SPAWN:
        return "subprocess"
    if action is PermissionAction.NETWORK_CONNECT:
        return "network"
    if action in {
        PermissionAction.GIT_PUSH,
        PermissionAction.GITHUB_PULL_REQUEST_CREATE,
    }:
        return "github"
    if action in {
        PermissionAction.MCP_SERVER_START,
        PermissionAction.MCP_TOOL_CALL,
    }:
        return "mcp"
    if action.value.startswith("schedule."):
        return "integration"
    return "filesystem"


def _risk(action: PermissionAction, *, protected: bool) -> str:
    if protected:
        return "blocked"
    if action in _HIGH_RISK_ACTIONS:
        return "high"
    if action in _MEDIUM_RISK_ACTIONS:
        return "medium"
    return "low"


def _consequence(action: PermissionAction) -> str:
    consequences = {
        PermissionAction.WORKSPACE_READ: "read_workspace_data",
        PermissionAction.WORKSPACE_WRITE: "change_workspace_files",
        PermissionAction.PROCESS_SPAWN: "start_a_local_process",
        PermissionAction.NETWORK_CONNECT: "contact_a_network_target",
        PermissionAction.MCP_SERVER_START: "start_or_connect_an_mcp_server",
        PermissionAction.MCP_TOOL_CALL: "invoke_an_mcp_tool",
        PermissionAction.GIT_COMMIT: "create_a_local_git_commit",
        PermissionAction.GIT_PUSH: "update_a_remote_git_ref",
        PermissionAction.GITHUB_PULL_REQUEST_CREATE: "create_a_github_pull_request",
        PermissionAction.GIT_APPLY: "apply_a_reviewed_change",
        PermissionAction.GIT_BRANCH_CREATE: "create_a_local_git_branch",
        PermissionAction.EXTERNAL_WRITE: "mutate_an_external_system",
        PermissionAction.SCHEDULE_CREATE: "create_automation_state",
        PermissionAction.SCHEDULE_ENABLE: "enable_future_automation_runs",
        PermissionAction.SCHEDULE_RUN_NOW: "queue_an_automation_run",
        PermissionAction.SCHEDULE_UNATTENDED_EDIT: "allow_an_unattended_edit",
    }
    return consequences[action]


def _why(
    request: ApprovalRequest,
    *,
    protected_reason: str | None,
) -> str:
    if protected_reason is not None:
        return protected_reason
    return (
        f"policy={request.policy_source};enforcement={request.enforcement.value};"
        f"owner={request.enforcement_owner or 'unknown'}"
    )


def _protected_reason(
    action: PermissionAction,
    preview: Mapping[str, Any],
) -> str | None:
    if action in _PROTECTED_ACTIONS:
        return "protected_action_requires_a_narrower_policy"
    for key, value in preview.items():
        if "path" not in str(key).lower() and key != "workspace":
            continue
        if isinstance(value, str) and _is_protected_path(value):
            return "protected_path_is_not_approvable"
    return None


def _is_protected_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    return any(part in _PROTECTED_PATH_PARTS for part in parts)


def _preview_binding(preview: Mapping[str, Any]) -> str | None:
    value = preview.get("approval_binding")
    if not isinstance(value, str) or not value.strip():
        return None
    return approval_binding_digest(value)


def _json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["APPROVAL_UX_SCHEMA_VERSION", "approval_ux_projection"]
