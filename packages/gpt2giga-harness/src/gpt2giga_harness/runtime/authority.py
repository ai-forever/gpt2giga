"""Versioned authority and approval schema for governed Harness actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import ipaddress
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from gpt2giga_harness.runtime.policy import EnforcementLevel


AUTHORITY_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_READ_OPERATIONS = frozenset({"inspect", "list", "read", "simulate", "status"})


class AuthorityResourceKind(str, Enum):
    """Independent resources that may receive authority."""

    FILESYSTEM = "filesystem"
    SUBPROCESS = "subprocess"
    NETWORK = "network"
    GITHUB = "github"
    BROWSER = "browser"
    MCP = "mcp"
    INTEGRATION = "integration"
    CHILD_AGENT = "child_agent"


class AuthorityLifetime(str, Enum):
    """Lifetime of one authority grant."""

    OPERATION = "operation"
    SESSION = "session"
    PERSISTED_POLICY = "persisted_policy"


class ApprovalPreset(str, Enum):
    """Operator-facing presets compiled into concrete scope rules."""

    ALWAYS_ASK = "always_ask"
    ASK_ON_WRITES = "ask_on_writes"
    ALLOW_REVIEWED = "allow_reviewed"


class AuthorityDecision(str, Enum):
    """Decision for one concrete scope after preset compilation."""

    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


class ReviewerKind(str, Enum):
    """Identity class responsible for an approval decision."""

    HUMAN = "human"
    AUTO_REVIEW = "auto_review"


class RevalidationReason(str, Enum):
    """Conditions that invalidate a prior approval."""

    EXPIRED = "expired"
    REVOKED = "revoked"
    STALE_PREVIEW = "stale_preview"
    TARGET_CHANGED = "target_changed"
    REDIRECT = "redirect"
    RETRY = "retry"


@dataclass(frozen=True)
class FilesystemTarget:
    """Workspace-rooted path target without an absolute private path."""

    root_id: str
    relative_path: str
    recursive: bool = False
    kind: AuthorityResourceKind = field(
        default=AuthorityResourceKind.FILESYSTEM,
        init=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "root_id": _identity(self.root_id, "filesystem root_id"),
            "relative_path": _relative_path(self.relative_path),
            "recursive": bool(self.recursive),
        }


@dataclass(frozen=True)
class SubprocessTarget:
    """Explicit executable plus content-addressed argv and cwd."""

    executable: str
    argv_sha256: str
    cwd_sha256: str
    kind: AuthorityResourceKind = field(
        default=AuthorityResourceKind.SUBPROCESS,
        init=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "executable": _identity(self.executable, "subprocess executable"),
            "argv_sha256": _sha256(self.argv_sha256, "subprocess argv"),
            "cwd_sha256": _sha256(self.cwd_sha256, "subprocess cwd"),
        }


@dataclass(frozen=True)
class NetworkTarget:
    """Exact network endpoint and redirect boundary."""

    host: str
    port: int
    protocol: str
    redirect_policy: str = "deny"
    kind: AuthorityResourceKind = field(
        default=AuthorityResourceKind.NETWORK,
        init=False,
    )

    def to_dict(self) -> dict[str, Any]:
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("network port is invalid")
        if self.redirect_policy not in {"deny", "same_origin"}:
            raise ValueError("network redirect_policy is invalid")
        return {
            "kind": self.kind.value,
            "host": _host(self.host),
            "port": int(self.port),
            "protocol": _token(self.protocol, "network protocol"),
            "redirect_policy": self.redirect_policy,
        }


@dataclass(frozen=True)
class GitHubTarget:
    """One repository without an ambient cross-repository grant."""

    repository: str
    kind: AuthorityResourceKind = field(
        default=AuthorityResourceKind.GITHUB,
        init=False,
    )

    def to_dict(self) -> dict[str, Any]:
        parts = self.repository.split("/")
        if len(parts) != 2 or any(not _TOKEN_RE.fullmatch(part) for part in parts):
            raise ValueError("github repository must be owner/name")
        return {"kind": self.kind.value, "repository": self.repository}


@dataclass(frozen=True)
class BrowserTarget:
    """Exact browser origin."""

    origin: str
    kind: AuthorityResourceKind = field(
        default=AuthorityResourceKind.BROWSER,
        init=False,
    )

    def to_dict(self) -> dict[str, Any]:
        parsed = urlsplit(self.origin)
        is_local_http = parsed.scheme == "http" and parsed.hostname == "localhost"
        if parsed.scheme != "https" and not is_local_http:
            raise ValueError("browser origin must be HTTPS or localhost")
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("browser origin is invalid")
        return {
            "kind": self.kind.value,
            "origin": f"{parsed.scheme}://{parsed.netloc}",
        }


@dataclass(frozen=True)
class McpTarget:
    """Exact managed MCP server and optional tool."""

    server_id: str
    tool_name: str | None = None
    kind: AuthorityResourceKind = field(default=AuthorityResourceKind.MCP, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "server_id": _identity(self.server_id, "MCP server_id"),
            "tool_name": (
                _identity(self.tool_name, "MCP tool_name")
                if self.tool_name is not None
                else None
            ),
        }


@dataclass(frozen=True)
class IntegrationTarget:
    """Exact integration definition and revision."""

    integration_id: str
    revision_sha256: str
    kind: AuthorityResourceKind = field(
        default=AuthorityResourceKind.INTEGRATION,
        init=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "integration_id": _identity(
                self.integration_id,
                "integration integration_id",
            ),
            "revision_sha256": _sha256(
                self.revision_sha256,
                "integration revision",
            ),
        }


@dataclass(frozen=True)
class ChildAgentTarget:
    """Child identity bound to its parent authority ceiling."""

    agent_id: str
    parent_ceiling_sha256: str
    kind: AuthorityResourceKind = field(
        default=AuthorityResourceKind.CHILD_AGENT,
        init=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "agent_id": _identity(self.agent_id, "child agent_id"),
            "parent_ceiling_sha256": _sha256(
                self.parent_ceiling_sha256,
                "child parent ceiling",
            ),
        }


AuthorityTarget = (
    FilesystemTarget
    | SubprocessTarget
    | NetworkTarget
    | GitHubTarget
    | BrowserTarget
    | McpTarget
    | IntegrationTarget
    | ChildAgentTarget
)


@dataclass(frozen=True)
class AuthorityScope:
    """One concrete target plus the exact operation classes requested."""

    target: AuthorityTarget
    operations: tuple[str, ...]
    schema_version: int = AUTHORITY_SCHEMA_VERSION
    scope_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORITY_SCHEMA_VERSION:
            raise ValueError("unsupported authority schema_version")
        if not isinstance(
            self.target,
            (
                FilesystemTarget,
                SubprocessTarget,
                NetworkTarget,
                GitHubTarget,
                BrowserTarget,
                McpTarget,
                IntegrationTarget,
                ChildAgentTarget,
            ),
        ):
            raise TypeError("authority scope target is invalid")
        normalized = tuple(
            sorted({_token(item, "authority operation") for item in self.operations})
        )
        if not normalized:
            raise ValueError("authority scope requires operations")
        object.__setattr__(self, "operations", normalized)
        object.__setattr__(self, "scope_sha256", _json_hash(self.semantic_payload()))

    @property
    def resource_kind(self) -> AuthorityResourceKind:
        """Return the independently modeled resource kind."""
        return self.target.kind

    def semantic_payload(self) -> dict[str, Any]:
        """Return the content-addressed semantics."""
        return {
            "schema_version": self.schema_version,
            "target": self.target.to_dict(),
            "operations": list(self.operations),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize one exact scope."""
        return {**self.semantic_payload(), "scope_sha256": self.scope_sha256}


@dataclass(frozen=True)
class ApprovalPolicy:
    """Preset, reviewer, and enforcement boundary selected independently."""

    preset: ApprovalPreset
    reviewer_kind: ReviewerKind
    reviewer_id: str
    policy_source: str
    enforcement: EnforcementLevel

    def __post_init__(self) -> None:
        if not isinstance(self.preset, ApprovalPreset):
            raise TypeError("approval preset is invalid")
        if not isinstance(self.reviewer_kind, ReviewerKind):
            raise TypeError("approval reviewer_kind is invalid")
        if not isinstance(self.enforcement, EnforcementLevel):
            raise TypeError("approval enforcement is invalid")
        _identity(self.reviewer_id, "approval reviewer_id")
        _identity(self.policy_source, "approval policy_source")


@dataclass(frozen=True)
class CompiledAuthorityRule:
    """Explicit policy result for one content-addressed scope."""

    scope_sha256: str
    preview_sha256: str
    decision: AuthorityDecision
    reviewer_kind: ReviewerKind
    reviewer_id: str
    policy_source: str
    enforcement: EnforcementLevel
    reviewed_preview_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_sha256": self.scope_sha256,
            "preview_sha256": self.preview_sha256,
            "decision": self.decision.value,
            "reviewer_kind": self.reviewer_kind.value,
            "reviewer_id": self.reviewer_id,
            "policy_source": self.policy_source,
            "enforcement": self.enforcement.value,
            "reviewed_preview_required": self.reviewed_preview_required,
        }


@dataclass(frozen=True)
class AuthorityGrant:
    """Bounded grant metadata; creation and persistence remain policy-owned."""

    id: str
    scope: AuthorityScope
    lifetime: AuthorityLifetime
    preview_sha256: str
    policy_source: str
    reviewer_kind: ReviewerKind
    reviewer_id: str
    enforcement: EnforcementLevel
    created_at: str
    operation_id: str | None = None
    session_id: str | None = None
    policy_id: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    parent_grant_id: str | None = None
    schema_version: int = AUTHORITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORITY_SCHEMA_VERSION:
            raise ValueError("unsupported authority grant schema_version")
        if not isinstance(self.lifetime, AuthorityLifetime):
            raise TypeError("authority grant lifetime is invalid")
        if not isinstance(self.reviewer_kind, ReviewerKind):
            raise TypeError("authority grant reviewer_kind is invalid")
        if not isinstance(self.enforcement, EnforcementLevel):
            raise TypeError("authority grant enforcement is invalid")
        _identity(self.id, "authority grant id")
        _sha256(self.preview_sha256, "authority preview")
        _identity(self.policy_source, "authority policy_source")
        _identity(self.reviewer_id, "authority reviewer_id")
        _timestamp(self.created_at, "authority created_at")
        if self.expires_at is not None:
            _timestamp(self.expires_at, "authority expires_at")
        if self.revoked_at is not None:
            _timestamp(self.revoked_at, "authority revoked_at")
        lifetime_id = {
            AuthorityLifetime.OPERATION: self.operation_id,
            AuthorityLifetime.SESSION: self.session_id,
            AuthorityLifetime.PERSISTED_POLICY: self.policy_id,
        }[self.lifetime]
        if lifetime_id is None:
            raise ValueError(f"{self.lifetime.value} grant requires its scope id")
        _identity(lifetime_id, f"{self.lifetime.value} scope id")
        if (
            self.lifetime is AuthorityLifetime.PERSISTED_POLICY
            and self.expires_at is None
        ):
            raise ValueError("persisted_policy grant requires expires_at")

    def to_dict(self) -> dict[str, Any]:
        """Serialize visible grant, expiry, revoke, policy, and reviewer evidence."""
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "scope": self.scope.to_dict(),
            "lifetime": self.lifetime.value,
            "preview_sha256": self.preview_sha256,
            "policy_source": self.policy_source,
            "reviewer_kind": self.reviewer_kind.value,
            "reviewer_id": self.reviewer_id,
            "enforcement": self.enforcement.value,
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "policy_id": self.policy_id,
            "parent_grant_id": self.parent_grant_id,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "created_at": self.created_at,
        }


def compile_approval_preset(
    policy: ApprovalPolicy,
    scopes: tuple[AuthorityScope, ...],
    *,
    preview_sha256: Mapping[str, str],
    reviewed_preview_sha256: Mapping[str, str] | None = None,
) -> tuple[CompiledAuthorityRule, ...]:
    """Compile one friendly preset into explicit per-scope policy rules."""
    if len({scope.scope_sha256 for scope in scopes}) != len(scopes):
        raise ValueError("authority scopes contain duplicates")
    expected_scopes = {scope.scope_sha256 for scope in scopes}
    if set(preview_sha256) != expected_scopes:
        raise ValueError("authority preview bindings must match scopes")
    reviewed = dict(reviewed_preview_sha256 or {})
    if not set(reviewed) <= expected_scopes:
        raise ValueError("reviewed authority preview contains an unknown scope")
    rules = []
    for scope in sorted(scopes, key=lambda item: item.scope_sha256):
        current_preview = _sha256(
            preview_sha256[scope.scope_sha256],
            "authority preset preview",
        )
        reviewed_required = policy.preset is ApprovalPreset.ALLOW_REVIEWED
        if policy.preset is ApprovalPreset.ALWAYS_ASK:
            decision = AuthorityDecision.ASK
        elif policy.preset is ApprovalPreset.ASK_ON_WRITES:
            decision = (
                AuthorityDecision.ALLOW
                if set(scope.operations) <= _READ_OPERATIONS
                else AuthorityDecision.ASK
            )
        else:
            decision = (
                AuthorityDecision.ALLOW
                if reviewed.get(scope.scope_sha256) == current_preview
                else AuthorityDecision.ASK
            )
        rules.append(
            CompiledAuthorityRule(
                scope_sha256=scope.scope_sha256,
                preview_sha256=current_preview,
                decision=decision,
                reviewer_kind=policy.reviewer_kind,
                reviewer_id=policy.reviewer_id,
                policy_source=policy.policy_source,
                enforcement=policy.enforcement,
                reviewed_preview_required=reviewed_required,
            )
        )
    return tuple(rules)


def child_scope_within_ceiling(
    child: AuthorityScope,
    parent: AuthorityScope,
) -> bool:
    """Return whether a child scope strictly preserves or narrows its ceiling."""
    return (
        child.resource_kind is parent.resource_kind
        and child.target.to_dict() == parent.target.to_dict()
        and set(child.operations) <= set(parent.operations)
    )


def revalidation_reasons(
    grant: AuthorityGrant,
    *,
    current_scope: AuthorityScope,
    current_preview_sha256: str,
    now: str,
    redirected: bool = False,
    retry: bool = False,
) -> tuple[RevalidationReason, ...]:
    """Return every reason a prior approval must not be reused."""
    _sha256(current_preview_sha256, "current authority preview")
    current_time = _timestamp(now, "current time")
    reasons = []
    if grant.revoked_at is not None:
        reasons.append(RevalidationReason.REVOKED)
    if (
        grant.expires_at is not None
        and _timestamp(grant.expires_at, "authority expires_at") <= current_time
    ):
        reasons.append(RevalidationReason.EXPIRED)
    if grant.preview_sha256 != current_preview_sha256:
        reasons.append(RevalidationReason.STALE_PREVIEW)
    if grant.scope.scope_sha256 != current_scope.scope_sha256:
        reasons.append(RevalidationReason.TARGET_CHANGED)
    if redirected:
        reasons.append(RevalidationReason.REDIRECT)
    if retry:
        reasons.append(RevalidationReason.RETRY)
    return tuple(reasons)


def authority_schema_manifest() -> dict[str, Any]:
    """Return the source-derived schema vocabulary used by UI/docs projections."""
    return {
        "schema_version": AUTHORITY_SCHEMA_VERSION,
        "resource_kinds": [item.value for item in AuthorityResourceKind],
        "lifetimes": [item.value for item in AuthorityLifetime],
        "approval_presets": [item.value for item in ApprovalPreset],
        "reviewer_kinds": [item.value for item in ReviewerKind],
        "decisions": [item.value for item in AuthorityDecision],
        "revalidation_reasons": [item.value for item in RevalidationReason],
        "child_authority_rule": "same_target_and_subset_operations",
        "auto_review_changes_enforcement": False,
        "content_free_preview_binding": "sha256",
    }


def _identity(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not _TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field_name} is invalid")
    return text


def _token(value: str, field_name: str) -> str:
    return _identity(value, field_name)


def _sha256(value: str, field_name: str) -> str:
    text = str(value)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field_name} sha256 is invalid")
    return text


def _relative_path(value: str) -> str:
    text = str(value).replace("\\", "/").strip("/")
    if not text or text.startswith("../") or "/../" in f"/{text}/":
        raise ValueError("filesystem relative_path is invalid")
    return text


def _host(value: str) -> str:
    text = str(value).strip().lower().rstrip(".")
    if not text or any(character in text for character in ("/", " ", "@")):
        raise ValueError("network host is invalid")
    if ":" in text:
        try:
            return ipaddress.ip_address(text).compressed
        except ValueError as exc:
            raise ValueError("network host is invalid") from exc
    return text


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
