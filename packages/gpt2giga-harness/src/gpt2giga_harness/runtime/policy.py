"""Unified permission policy and approval contracts for Harness-owned actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Any, Mapping, Protocol

from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.tools.policy import PolicyDecision


class PermissionAction(str, Enum):
    """Stable action taxonomy shared by jobs, tools, and schedules."""

    WORKSPACE_READ = "workspace.read"
    WORKSPACE_WRITE = "workspace.write"
    PROCESS_SPAWN = "process.spawn"
    NETWORK_CONNECT = "network.connect"
    MCP_SERVER_START = "mcp.server.start"
    MCP_TOOL_CALL = "mcp.tool.call"
    GIT_APPLY = "git.apply"
    GIT_BRANCH_CREATE = "git.branch.create"
    EXTERNAL_WRITE = "external.write"
    SCHEDULE_CREATE = "schedule.create"
    SCHEDULE_ENABLE = "schedule.enable"
    SCHEDULE_RUN_NOW = "schedule.run_now"
    SCHEDULE_UNATTENDED_EDIT = "schedule.unattended_edit"


class EnforcementLevel(str, Enum):
    """Boundary at which a decision can actually be enforced."""

    ENFORCED_BY_HARNESS = "enforced_by_harness"
    DELEGATED_TO_CLI_SANDBOX = "delegated_to_cli_sandbox"
    ADVISORY_OR_UNOBSERVABLE = "advisory_or_unobservable"


class ApprovalDecision(str, Enum):
    """Persisted user decision for one approval request."""

    ALLOW_ONCE = "allow_once"
    ALLOW_RUN = "allow_run"
    ALLOW_PROJECT = "allow_project"
    DENY = "deny"


class PolicyAuditPhase(str, Enum):
    """Immutable lifecycle phase for one governed operation."""

    RESOLUTION = "resolution"
    DECISION = "decision"
    ENFORCEMENT = "enforcement"


REVIEWED_PROMOTION_APPLY_OWNER = "reviewed_promotion.run_apply"
REVIEWED_PROMOTION_BRANCH_OWNER = "reviewed_promotion.branch_create"
REVIEWED_PROMOTION_MERGE_OWNER = "reviewed_promotion.workflow_merge_apply"


@dataclass(frozen=True)
class PermissionProfile:
    """Named immutable rule set selected at submission time."""

    id: str
    rules: Mapping[PermissionAction, PolicyDecision]
    default: PolicyDecision = PolicyDecision.ASK

    def decision_for(self, action: PermissionAction) -> PolicyDecision:
        """Return the explicit rule or the profile default."""
        return self.rules.get(action, self.default)


@dataclass(frozen=True)
class PolicyContext:
    """Redaction-safe scope used to resolve grants and create approvals."""

    project_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    reason: str = ""
    preview: Mapping[str, Any] | None = None
    approval_binding: str | None = None
    enforcement_owner: str | None = None


@dataclass(frozen=True)
class PolicyResolution:
    """Resolved decision with its auditable source and enforcement boundary."""

    action: PermissionAction
    decision: PolicyDecision
    enforcement: EnforcementLevel
    policy_source: str


@dataclass(frozen=True)
class ApprovalRequest:
    """One persisted approval inbox item."""

    id: str
    action: PermissionAction
    status: ApprovalStatus
    enforcement: EnforcementLevel
    policy_source: str
    enforcement_owner: str | None
    reason: str
    preview: Mapping[str, Any]
    created_at: str
    expires_at: str | None = None
    decided_at: str | None = None
    decision: ApprovalDecision | None = None
    project_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None


@dataclass(frozen=True)
class ApprovalGrant:
    """One allow-once, run, or expiring project grant."""

    id: str
    request_id: str
    action: PermissionAction
    scope_type: str
    scope_id: str
    created_at: str
    expires_at: str | None = None
    uses_remaining: int | None = None


@dataclass(frozen=True)
class PolicyAuditEvent:
    """One append-only, hash-chained policy operation event."""

    id: str
    operation_id: str
    sequence: int
    action: PermissionAction
    phase: PolicyAuditPhase
    decision: str
    enforcement: EnforcementLevel
    enforcement_owner: str
    policy_source: str
    approval_request_id: str
    approval_grant_id: str | None
    approval_binding_sha256: str | None
    project_id: str | None
    session_id: str | None
    run_id: str | None
    job_id: str | None
    evidence: Mapping[str, Any]
    previous_event_sha256: str | None
    event_sha256: str
    created_at: str


def approval_request_to_dict(request: ApprovalRequest) -> dict[str, Any]:
    """Serialize one approval without secret-bearing values."""
    return {
        "id": request.id,
        "action": request.action.value,
        "status": request.status.value,
        "enforcement": request.enforcement.value,
        "policy_source": request.policy_source,
        "enforcement_owner": request.enforcement_owner,
        "reason": request.reason,
        "preview": redacted_policy_preview(request.preview),
        "project_id": request.project_id,
        "session_id": request.session_id,
        "run_id": request.run_id,
        "job_id": request.job_id,
        "decision": request.decision.value if request.decision else None,
        "expires_at": request.expires_at,
        "decided_at": request.decided_at,
        "created_at": request.created_at,
    }


def policy_audit_event_to_dict(event: PolicyAuditEvent) -> dict[str, Any]:
    """Serialize immutable policy evidence without raw bindings or secrets."""
    return {
        "id": event.id,
        "operation_id": event.operation_id,
        "sequence": event.sequence,
        "action": event.action.value,
        "phase": event.phase.value,
        "decision": event.decision,
        "enforcement": event.enforcement.value,
        "enforcement_owner": event.enforcement_owner,
        "policy_source": event.policy_source,
        "approval_request_id": event.approval_request_id,
        "approval_grant_id": event.approval_grant_id,
        "approval_binding_sha256": event.approval_binding_sha256,
        "project_id": event.project_id,
        "session_id": event.session_id,
        "run_id": event.run_id,
        "job_id": event.job_id,
        "evidence": redact_for_storage(dict(event.evidence)),
        "previous_event_sha256": event.previous_event_sha256,
        "event_sha256": event.event_sha256,
        "created_at": event.created_at,
    }


def approval_grant_to_dict(grant: ApprovalGrant) -> dict[str, Any]:
    """Serialize one redaction-safe approval grant."""
    return {
        "id": grant.id,
        "request_id": grant.request_id,
        "action": grant.action.value,
        "scope_type": grant.scope_type,
        "scope_id": grant.scope_id,
        "uses_remaining": grant.uses_remaining,
        "expires_at": grant.expires_at,
        "created_at": grant.created_at,
    }


class GrantStore(Protocol):
    """Narrow storage contract required by the policy engine."""

    def consume_matching_approval_grant(
        self,
        *,
        action: PermissionAction | str,
        project_id: str | None,
        run_id: str | None,
        job_id: str | None,
        approval_binding: str | None = None,
        enforcement_owner: str | None = None,
    ) -> bool:
        raise NotImplementedError


INTERACTIVE_PROFILE = PermissionProfile(
    id="interactive",
    rules={
        PermissionAction.WORKSPACE_READ: PolicyDecision.ALLOW,
        PermissionAction.WORKSPACE_WRITE: PolicyDecision.ALLOW,
        PermissionAction.PROCESS_SPAWN: PolicyDecision.ALLOW,
        PermissionAction.NETWORK_CONNECT: PolicyDecision.ALLOW,
        PermissionAction.MCP_SERVER_START: PolicyDecision.ASK,
        PermissionAction.MCP_TOOL_CALL: PolicyDecision.ASK,
        PermissionAction.GIT_APPLY: PolicyDecision.ASK,
        PermissionAction.GIT_BRANCH_CREATE: PolicyDecision.ASK,
        PermissionAction.EXTERNAL_WRITE: PolicyDecision.ASK,
        PermissionAction.SCHEDULE_CREATE: PolicyDecision.ASK,
        PermissionAction.SCHEDULE_ENABLE: PolicyDecision.ASK,
        PermissionAction.SCHEDULE_RUN_NOW: PolicyDecision.ASK,
        PermissionAction.SCHEDULE_UNATTENDED_EDIT: PolicyDecision.DENY,
    },
)

REVIEW_EVERY_ACTION_PROFILE = PermissionProfile(
    id="review_every_action",
    rules={
        PermissionAction.WORKSPACE_READ: PolicyDecision.ALLOW,
        PermissionAction.PROCESS_SPAWN: PolicyDecision.ASK,
    },
    default=PolicyDecision.ASK,
)

UNATTENDED_PROFILE = PermissionProfile(
    id="unattended",
    rules={
        PermissionAction.WORKSPACE_READ: PolicyDecision.ALLOW,
        PermissionAction.PROCESS_SPAWN: PolicyDecision.ALLOW,
        PermissionAction.WORKSPACE_WRITE: PolicyDecision.ASK,
        PermissionAction.NETWORK_CONNECT: PolicyDecision.ASK,
        PermissionAction.SCHEDULE_UNATTENDED_EDIT: PolicyDecision.ASK,
    },
    default=PolicyDecision.DENY,
)

_PROFILES = {
    profile.id: profile
    for profile in (
        INTERACTIVE_PROFILE,
        REVIEW_EVERY_ACTION_PROFILE,
        UNATTENDED_PROFILE,
    )
}


def permission_profile(value: Any, *, origin: str = "manual") -> PermissionProfile:
    """Resolve a built-in profile without accepting caller-authored allow rules."""
    default_id = (
        "unattended" if origin not in {"manual", "interactive"} else "interactive"
    )
    profile_id = str(value or default_id).strip().lower().replace("-", "_")
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown permission profile: {profile_id}") from exc


def redacted_policy_preview(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a bounded redacted preview safe for approval persistence and APIs."""
    redacted = redact_for_storage(dict(value or {}))
    if not isinstance(redacted, Mapping):
        return {}
    return {str(key): item for key, item in list(redacted.items())[:40]}


def approval_binding_digest(value: str) -> str:
    """Hash one opaque approval binding before persistence or comparison."""
    text = str(value).strip()
    if not text:
        raise ValueError("approval_binding must not be empty")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PolicyEngine:
    """Resolve built-in rules plus persisted one/run/project grants."""

    def __init__(self, grant_store: GrantStore | None = None) -> None:
        self.grant_store = grant_store

    def resolve(
        self,
        action: PermissionAction | str,
        *,
        profile: PermissionProfile,
        context: PolicyContext,
        enforcement: EnforcementLevel = EnforcementLevel.ENFORCED_BY_HARNESS,
        consume_grant: bool = True,
    ) -> PolicyResolution:
        """Resolve one action, consuming a matching single-use grant when present."""
        parsed_action = PermissionAction(action)
        if consume_grant and self.grant_store is not None:
            granted = self.grant_store.consume_matching_approval_grant(
                action=parsed_action,
                project_id=context.project_id,
                run_id=context.run_id,
                job_id=context.job_id,
                approval_binding=context.approval_binding,
                enforcement_owner=context.enforcement_owner,
            )
            if granted:
                return PolicyResolution(
                    action=parsed_action,
                    decision=PolicyDecision.ALLOW,
                    enforcement=enforcement,
                    policy_source="approval_grant",
                )
        return PolicyResolution(
            action=parsed_action,
            decision=profile.decision_for(parsed_action),
            enforcement=enforcement,
            policy_source=f"profile:{profile.id}",
        )
