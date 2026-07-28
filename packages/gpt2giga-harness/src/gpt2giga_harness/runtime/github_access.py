"""Fail-closed GitHub authority distinct from local Git operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any

from gpt2giga_harness.runtime.authority import (
    AuthorityGrant,
    AuthorityLifetime,
    AuthorityScope,
    GitHubTarget,
)
from gpt2giga_harness.runtime.policy import EnforcementLevel


GITHUB_ACCESS_SCHEMA_VERSION = 1
GITHUB_WRITE_PREVIEW_TTL_SECONDS = 5 * 60
MAX_GITHUB_WRITE_PAYLOAD_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_REPOSITORY_PART_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]{0,99})$")
_RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")


class GitHubAccessDenied(PermissionError):
    """Content-free denial raised before a GitHub API or CLI side effect."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class GitHubAuthoritySurface(str, Enum):
    """Execution surfaces classified independently from local Git."""

    LOCAL_GIT = "local_git"
    GITHUB_API = "github_api"
    GITHUB_CLI = "github_cli"


class GitHubOperationClass(str, Enum):
    """Bounded GitHub operation classes admitted by schema version 1."""

    ORIENTATION_READ = "orientation.read"
    ISSUE_WRITE = "issue.write"
    COMMENT_WRITE = "comment.write"
    PULL_REQUEST_WRITE = "pull_request.write"
    RELEASE_WRITE = "release.write"

    @property
    def is_write(self) -> bool:
        """Return whether the operation can mutate hosted GitHub state."""
        return self is not GitHubOperationClass.ORIENTATION_READ


class GitHubCredentialSource(str, Enum):
    """Credential owners identified without exposing credential material."""

    GH_CLI_ACTIVE_ACCOUNT = "gh_cli_active_account"
    GITHUB_APP_INSTALLATION = "github_app_installation"
    DEPLOYMENT_ENVIRONMENT = "deployment_environment"


@dataclass(frozen=True)
class GitHubCredentialBinding:
    """Opaque current credential identity and permission-set evidence."""

    source: GitHubCredentialSource
    host: str
    principal_sha256: str
    permission_set_sha256: str
    expires_at: str | None = None
    schema_version: int = GITHUB_ACCESS_SCHEMA_VERSION
    binding_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != GITHUB_ACCESS_SCHEMA_VERSION:
            raise ValueError("unsupported GitHub credential schema_version")
        if not isinstance(self.source, GitHubCredentialSource):
            raise TypeError("GitHub credential source is invalid")
        host = _host(self.host)
        principal = _sha256(self.principal_sha256, "GitHub credential principal")
        permissions = _sha256(
            self.permission_set_sha256,
            "GitHub credential permission set",
        )
        if self.expires_at is not None:
            _timestamp(self.expires_at, "GitHub credential expires_at")
        semantic = {
            "schema_version": self.schema_version,
            "source": self.source.value,
            "host": host,
            "principal_sha256": principal,
            "permission_set_sha256": permissions,
            "expires_at": self.expires_at,
        }
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "principal_sha256", principal)
        object.__setattr__(self, "permission_set_sha256", permissions)
        object.__setattr__(self, "binding_sha256", _json_hash(semantic))

    def to_dict(self) -> dict[str, Any]:
        """Serialize only opaque credential identity and capability evidence."""
        return {
            "schema_version": self.schema_version,
            "source": self.source.value,
            "host": self.host,
            "principal_sha256": self.principal_sha256,
            "permission_set_sha256": self.permission_set_sha256,
            "expires_at": self.expires_at,
            "binding_sha256": self.binding_sha256,
        }


@dataclass(frozen=True)
class GitHubCapabilityRequest:
    """One repository-bound read or exact hosted-write intent."""

    repository: str
    operation: GitHubOperationClass
    surface: GitHubAuthoritySurface
    credential: GitHubCredentialBinding
    resource_id: str | None = None
    payload_bytes: int = 0
    payload_sha256: str | None = None
    preview_created_at: str | None = None
    preview_expires_at: str | None = None
    schema_version: int = GITHUB_ACCESS_SCHEMA_VERSION
    scope: AuthorityScope = field(init=False)
    preview_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != GITHUB_ACCESS_SCHEMA_VERSION:
            raise ValueError("unsupported GitHub access schema_version")
        if not isinstance(self.operation, GitHubOperationClass):
            raise TypeError("GitHub operation is invalid")
        if not isinstance(self.surface, GitHubAuthoritySurface):
            raise TypeError("GitHub authority surface is invalid")
        if not isinstance(self.credential, GitHubCredentialBinding):
            raise TypeError("GitHub credential binding is invalid")
        if self.surface is GitHubAuthoritySurface.LOCAL_GIT:
            raise ValueError("local Git must use local Git authority, not GitHub")

        repository = _repository(self.repository)
        resource_id = (
            _resource_id(self.resource_id) if self.resource_id is not None else None
        )
        payload_bytes = _payload_size(self.payload_bytes)
        payload_sha256 = (
            _sha256(self.payload_sha256, "GitHub write payload")
            if self.payload_sha256 is not None
            else None
        )
        created_at = self.preview_created_at
        expires_at = self.preview_expires_at
        if self.operation.is_write:
            if resource_id is None:
                raise ValueError("GitHub write requires a content-free resource id")
            if payload_sha256 is None:
                raise ValueError("GitHub write requires a payload sha256")
            if created_at is None or expires_at is None:
                raise ValueError("GitHub write requires a fresh preview window")
            created = _timestamp(created_at, "GitHub preview created_at")
            expires = _timestamp(expires_at, "GitHub preview expires_at")
            lifetime = (expires - created).total_seconds()
            if not 0 < lifetime <= GITHUB_WRITE_PREVIEW_TTL_SECONDS:
                raise ValueError("GitHub write preview window is invalid")
        elif (
            any(
                value is not None
                for value in (resource_id, payload_sha256, created_at, expires_at)
            )
            or payload_bytes
        ):
            raise ValueError("GitHub orientation must not contain write intent")

        scope = AuthorityScope(
            target=GitHubTarget(repository),
            operations=(self.operation.value,),
        )
        semantic = {
            "schema_version": self.schema_version,
            "scope_sha256": scope.scope_sha256,
            "surface": self.surface.value,
            "credential_binding_sha256": self.credential.binding_sha256,
            "resource_id": resource_id,
            "payload_bytes": payload_bytes,
            "payload_sha256": payload_sha256,
            "preview_created_at": created_at,
            "preview_expires_at": expires_at,
        }
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "payload_bytes", payload_bytes)
        object.__setattr__(self, "payload_sha256", payload_sha256)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "preview_sha256", _json_hash(semantic))

    @property
    def approval_binding(self) -> str | None:
        """Return an exact binding for writes; reads need no mutation approval."""
        if not self.operation.is_write:
            return None
        return f"github-capability-v1:{self.preview_sha256}"

    def approval_preview(self) -> dict[str, Any]:
        """Return a content-free approval preview with no body or credential."""
        return {
            "schema_version": self.schema_version,
            "repository": {"name_with_owner": self.repository},
            "operation": self.operation.value,
            "surface": self.surface.value,
            "credential_source": self.credential.source.value,
            "resource_id_sha256": (
                _text_hash(self.resource_id) if self.resource_id is not None else None
            ),
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
            "preview_created_at": self.preview_created_at,
            "preview_expires_at": self.preview_expires_at,
            "approval_binding": self.approval_binding,
        }


@dataclass(frozen=True)
class GitHubAccessTicket:
    """Short-lived semantic authorization checked again before dispatch."""

    repository: str
    operation: GitHubOperationClass
    surface: GitHubAuthoritySurface
    credential_source: GitHubCredentialSource
    credential_binding_sha256: str
    scope_sha256: str
    preview_sha256: str
    authorized_at: str
    expires_at: str | None
    grant_id: str | None
    policy_source: str
    reviewer_kind: str
    reviewer_id_sha256: str | None
    resource_id_sha256: str | None
    payload_bytes: int
    payload_sha256: str | None

    def validate_before_dispatch(
        self,
        request: GitHubCapabilityRequest,
        *,
        current_credential_binding_sha256: str,
        now: str,
        retry: bool = False,
    ) -> dict[str, Any]:
        """Revalidate target, preview, credential, expiry, and retry at dispatch."""
        current = _timestamp(now, "GitHub dispatch time")
        if current < _timestamp(self.authorized_at, "GitHub authorized_at"):
            raise GitHubAccessDenied("github_ticket_clock_moved_backwards")
        if self.expires_at is not None and current >= _timestamp(
            self.expires_at,
            "GitHub ticket expires_at",
        ):
            raise GitHubAccessDenied("github_ticket_is_expired")
        if retry and request.operation.is_write:
            raise GitHubAccessDenied("github_write_retry_requires_fresh_preview")
        if request.scope.scope_sha256 != self.scope_sha256:
            raise GitHubAccessDenied("github_target_or_operation_changed")
        if request.preview_sha256 != self.preview_sha256:
            raise GitHubAccessDenied("github_preview_changed")
        current_binding = _sha256(
            current_credential_binding_sha256,
            "current GitHub credential binding",
        )
        if (
            request.credential.binding_sha256 != self.credential_binding_sha256
            or current_binding != self.credential_binding_sha256
        ):
            raise GitHubAccessDenied("github_credential_changed")
        return self.audit_receipt(outcome="dispatch_validated")

    def audit_receipt(self, *, outcome: str = "authorized") -> dict[str, Any]:
        """Return bounded evidence without raw credentials or write content."""
        return {
            "schema_version": GITHUB_ACCESS_SCHEMA_VERSION,
            "repository": self.repository,
            "operation": self.operation.value,
            "surface": self.surface.value,
            "credential_source": self.credential_source.value,
            "credential_binding_sha256": self.credential_binding_sha256,
            "scope_sha256": self.scope_sha256,
            "preview_sha256": self.preview_sha256,
            "resource_id_sha256": self.resource_id_sha256,
            "payload_bytes": self.payload_bytes,
            "payload_sha256": self.payload_sha256,
            "grant_id": self.grant_id,
            "policy_source": self.policy_source,
            "reviewer_kind": self.reviewer_kind,
            "reviewer_id_sha256": self.reviewer_id_sha256,
            "authorized_at": self.authorized_at,
            "expires_at": self.expires_at,
            "network_authority_required": True,
            "outcome": outcome,
        }


def authorize_github_capability(
    request: GitHubCapabilityRequest,
    grant: AuthorityGrant | None,
    *,
    current_credential_binding_sha256: str,
    now: str,
    retry: bool = False,
) -> GitHubAccessTicket:
    """Authorize read orientation or one exact hosted write without executing it."""
    current_time = _timestamp(now, "GitHub authorization time")
    current_binding = _sha256(
        current_credential_binding_sha256,
        "current GitHub credential binding",
    )
    if current_binding != request.credential.binding_sha256:
        raise GitHubAccessDenied("github_credential_changed")
    if (
        request.credential.expires_at is not None
        and _timestamp(
            request.credential.expires_at,
            "GitHub credential expires_at",
        )
        <= current_time
    ):
        raise GitHubAccessDenied("github_credential_is_expired")

    if not request.operation.is_write:
        if grant is not None:
            raise GitHubAccessDenied(
                "github_orientation_is_independent_of_mutation_grants"
            )
        return GitHubAccessTicket(
            repository=request.repository,
            operation=request.operation,
            surface=request.surface,
            credential_source=request.credential.source,
            credential_binding_sha256=request.credential.binding_sha256,
            scope_sha256=request.scope.scope_sha256,
            preview_sha256=request.preview_sha256,
            authorized_at=now,
            expires_at=request.credential.expires_at,
            grant_id=None,
            policy_source="github.orientation.read_only",
            reviewer_kind="none",
            reviewer_id_sha256=None,
            resource_id_sha256=None,
            payload_bytes=0,
            payload_sha256=None,
        )

    if retry:
        raise GitHubAccessDenied("github_write_retry_requires_fresh_preview")
    if grant is None:
        raise GitHubAccessDenied("github_write_requires_grant")
    if grant.enforcement is not EnforcementLevel.ENFORCED_BY_HARNESS:
        raise GitHubAccessDenied("github_grant_is_not_harness_enforced")
    if grant.lifetime is not AuthorityLifetime.OPERATION:
        raise GitHubAccessDenied("github_write_requires_operation_grant")
    if grant.revoked_at is not None:
        raise GitHubAccessDenied("github_grant_is_revoked")
    if grant.expires_at is None:
        raise GitHubAccessDenied("github_grant_requires_expiry")
    grant_expiry = _timestamp(grant.expires_at, "GitHub grant expires_at")
    if grant_expiry <= current_time:
        raise GitHubAccessDenied("github_grant_is_expired")
    if request.scope.scope_sha256 != grant.scope.scope_sha256:
        raise GitHubAccessDenied("github_scope_does_not_match_grant")
    if request.preview_sha256 != grant.preview_sha256:
        raise GitHubAccessDenied("github_preview_does_not_match_grant")

    created = _timestamp(request.preview_created_at or "", "GitHub preview created_at")
    preview_expiry = _timestamp(
        request.preview_expires_at or "",
        "GitHub preview expires_at",
    )
    if current_time < created:
        raise GitHubAccessDenied("github_preview_clock_moved_backwards")
    if current_time >= preview_expiry:
        raise GitHubAccessDenied("github_write_preview_is_expired")
    credential_expiry = (
        _timestamp(request.credential.expires_at, "GitHub credential expires_at")
        if request.credential.expires_at is not None
        else None
    )
    expires_at = min(
        item for item in (grant_expiry, preview_expiry, credential_expiry) if item
    ).isoformat()
    return GitHubAccessTicket(
        repository=request.repository,
        operation=request.operation,
        surface=request.surface,
        credential_source=request.credential.source,
        credential_binding_sha256=request.credential.binding_sha256,
        scope_sha256=request.scope.scope_sha256,
        preview_sha256=request.preview_sha256,
        authorized_at=now,
        expires_at=expires_at,
        grant_id=grant.id,
        policy_source=grant.policy_source,
        reviewer_kind=grant.reviewer_kind.value,
        reviewer_id_sha256=_text_hash(grant.reviewer_id),
        resource_id_sha256=_text_hash(request.resource_id or ""),
        payload_bytes=request.payload_bytes,
        payload_sha256=request.payload_sha256,
    )


def github_access_manifest() -> dict[str, Any]:
    """Return the source-owned G4-03 authority and privacy contract."""
    return {
        "schema_version": GITHUB_ACCESS_SCHEMA_VERSION,
        "authority_surfaces": {
            "local_git": "separate_non_github_authority",
            "github_api": "github_capability",
            "github_cli": "github_capability",
        },
        "orientation": {
            "operation": GitHubOperationClass.ORIENTATION_READ.value,
            "mutation_grant_required": False,
            "network_authority_required": True,
            "owner": "github_environments.GitHubEnvironmentService",
        },
        "write_operation_classes": [
            item.value for item in GitHubOperationClass if item.is_write
        ],
        "credential_sources": [item.value for item in GitHubCredentialSource],
        "write_grant": {
            "lifetime": AuthorityLifetime.OPERATION.value,
            "enforcement": EnforcementLevel.ENFORCED_BY_HARNESS.value,
            "expiry_required": True,
            "fresh_preview_required": True,
            "preview_ttl_seconds": GITHUB_WRITE_PREVIEW_TTL_SECONDS,
            "retry_requires_fresh_preview": True,
        },
        "receipt_omits": [
            "credential",
            "principal",
            "write_body",
            "direct_personal_data",
            "contact_data",
            "payment_data",
        ],
        "existing_pull_request_owner": (
            "environment_pull_requests.GovernedEnvironmentPullRequestService"
        ),
        "live_github_side_effect": False,
    }


def _repository(value: str) -> str:
    text = str(value).strip().lower()
    parts = text.split("/")
    if len(parts) != 2 or any(
        _REPOSITORY_PART_RE.fullmatch(part) is None for part in parts
    ):
        raise ValueError("GitHub repository must be canonical owner/name")
    return text


def _host(value: str) -> str:
    text = str(value).strip().lower().rstrip(".")
    if (
        not text
        or len(text) > 253
        or any(character in text for character in ("/", " ", "@", ":"))
    ):
        raise ValueError("GitHub credential host is invalid")
    labels = text.split(".")
    if len(labels) < 2 or any(
        _DNS_LABEL_RE.fullmatch(label) is None for label in labels
    ):
        raise ValueError("GitHub credential host is invalid")
    return text


def _resource_id(value: str) -> str:
    text = str(value).strip().lower()
    if _RESOURCE_ID_RE.fullmatch(text) is None:
        raise ValueError("GitHub resource id is invalid")
    return text


def _payload_size(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_GITHUB_WRITE_PAYLOAD_BYTES
    ):
        raise ValueError("GitHub write payload size is invalid")
    return value


def _sha256(value: str, field_name: str) -> str:
    text = str(value)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{field_name} sha256 is invalid")
    return text


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _text_hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _json_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "GITHUB_ACCESS_SCHEMA_VERSION",
    "GITHUB_WRITE_PREVIEW_TTL_SECONDS",
    "GitHubAccessDenied",
    "GitHubAccessTicket",
    "GitHubAuthoritySurface",
    "GitHubCapabilityRequest",
    "GitHubCredentialBinding",
    "GitHubCredentialSource",
    "GitHubOperationClass",
    "authorize_github_capability",
    "github_access_manifest",
]
