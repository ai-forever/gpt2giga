"""Provider-neutral identities and immutable execution snapshot contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


EXECUTION_SNAPSHOT_SCHEMA_VERSION = 1
EMPTY_EXTENSION_SNAPSHOT_HASH = hashlib.sha256(b'{"extensions":[]}').hexdigest()
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,255}\Z")


class ExecutionTransport(str, Enum):
    """Describe the effective transport used for one execution."""

    NATIVE_STRUCTURED = "native_structured"
    NATIVE_TERMINAL = "native_terminal"
    ONE_SHOT = "one_shot"


class InteractionMode(str, Enum):
    """Describe whether a live execution accepts supported input."""

    INTERACTIVE = "interactive"
    BATCH = "batch"


class RuntimeOwnership(str, Enum):
    """Describe whether execution ownership survives the initiating request."""

    REQUEST_BOUND = "request_bound"
    DURABLE = "durable"


class ExecutionClassificationStatus(str, Enum):
    """Describe how canonical execution axes were established."""

    EXPLICIT = "explicit"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"
    CONTRADICTORY = "contradictory"


@dataclass(frozen=True, order=True)
class ProviderRef:
    """Minimal immutable identity and revision of one model provider profile."""

    id: str
    revision: str

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="provider id")
        _validate_identity(self.revision, field_name="provider revision")


@dataclass(frozen=True, order=True)
class RouteRef:
    """Minimal immutable route identity bound to an exact provider revision."""

    id: str
    revision: str
    provider: ProviderRef

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="route id")
        _validate_identity(self.revision, field_name="route revision")
        if not isinstance(self.provider, ProviderRef):
            raise ValueError("route provider must be a ProviderRef")


@dataclass(frozen=True, order=True)
class SnapshotEvidenceRef:
    """Content-free reference to probed compatibility or capability evidence."""

    id: str
    revision: str
    status: str
    source: str

    def __post_init__(self) -> None:
        _validate_identity(self.id, field_name="evidence id")
        _validate_identity(self.revision, field_name="evidence revision")
        _validate_identity(self.status, field_name="evidence status")
        _validate_identity(self.source, field_name="evidence source")


@dataclass(frozen=True)
class ExecutionClassification:
    """Evidence-based classification for explicit or legacy execution state."""

    status: ExecutionClassificationStatus
    source: str
    reason_code: str | None = None
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ExecutionClassificationStatus):
            raise ValueError("execution classification status is invalid")
        _validate_identity(self.source, field_name="classification source")
        if self.reason_code is not None:
            _validate_identity(
                self.reason_code,
                field_name="classification reason_code",
            )
        normalized = tuple(sorted(self.evidence))
        if len(set(normalized)) != len(normalized):
            raise ValueError("classification evidence contains duplicates")
        for item in normalized:
            _validate_identity(item, field_name="classification evidence")
        object.__setattr__(self, "evidence", normalized)
        if (
            self.status
            in {
                ExecutionClassificationStatus.AMBIGUOUS,
                ExecutionClassificationStatus.CONTRADICTORY,
            }
            and self.reason_code is None
        ):
            raise ValueError(
                "ambiguous or contradictory classification requires reason_code"
            )
        if self.status is ExecutionClassificationStatus.INFERRED and not self.evidence:
            raise ValueError("inferred classification requires immutable evidence")


@dataclass(frozen=True)
class ExecutionBudgets:
    """Deterministic limits that participate in execution continuation identity."""

    timeout_seconds: int | None = None
    retry_limit: int = 0
    cost_limit_microunits: int | None = None
    token_limit: int | None = None
    runtime_seconds: int | None = None

    def __post_init__(self) -> None:
        _validate_optional_non_negative_int(
            self.timeout_seconds,
            field_name="timeout_seconds",
        )
        _validate_non_negative_int(self.retry_limit, field_name="retry_limit")
        _validate_optional_non_negative_int(
            self.cost_limit_microunits,
            field_name="cost_limit_microunits",
        )
        _validate_optional_non_negative_int(
            self.token_limit,
            field_name="token_limit",
        )
        _validate_optional_non_negative_int(
            self.runtime_seconds,
            field_name="runtime_seconds",
        )


@dataclass(frozen=True)
class ExecutionSnapshot:
    """Versioned immutable identity for one provider-neutral execution."""

    provider: ProviderRef
    route: RouteRef
    harness_id: str
    harness_version: str
    transport: ExecutionTransport | None
    interaction_mode: InteractionMode | None
    runtime_ownership: RuntimeOwnership | None
    workspace_id: str
    worktree_id: str | None
    permission_profile: str
    extension_snapshot_hash: str
    budgets: ExecutionBudgets = field(default_factory=ExecutionBudgets)
    compatibility_evidence: tuple[SnapshotEvidenceRef, ...] = ()
    capability_evidence: tuple[SnapshotEvidenceRef, ...] = ()
    classification: ExecutionClassification = field(
        default_factory=lambda: ExecutionClassification(
            status=ExecutionClassificationStatus.EXPLICIT,
            source="explicit_request",
        )
    )
    schema_version: int = EXECUTION_SNAPSHOT_SCHEMA_VERSION
    snapshot_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported execution snapshot schema_version")
        if not isinstance(self.provider, ProviderRef):
            raise ValueError("snapshot provider must be a ProviderRef")
        if not isinstance(self.route, RouteRef):
            raise ValueError("snapshot route must be a RouteRef")
        if self.route.provider != self.provider:
            raise ValueError("route provider does not match snapshot provider")
        _validate_identity(self.harness_id, field_name="harness id")
        _validate_identity(self.harness_version, field_name="harness version")
        _validate_identity(self.workspace_id, field_name="workspace id")
        if self.worktree_id is not None:
            _validate_identity(self.worktree_id, field_name="worktree id")
        _validate_identity(
            self.permission_profile,
            field_name="permission profile",
        )
        _validate_hash(
            self.extension_snapshot_hash,
            field_name="extension_snapshot_hash",
        )
        if not isinstance(self.budgets, ExecutionBudgets):
            raise ValueError("snapshot budgets must be ExecutionBudgets")
        if not isinstance(self.classification, ExecutionClassification):
            raise ValueError("snapshot classification must be ExecutionClassification")
        compatibility = _normalize_evidence(
            self.compatibility_evidence,
            field_name="compatibility",
        )
        capabilities = _normalize_evidence(
            self.capability_evidence,
            field_name="capability",
        )
        object.__setattr__(self, "compatibility_evidence", compatibility)
        object.__setattr__(self, "capability_evidence", capabilities)
        self._validate_execution_axes()
        object.__setattr__(self, "snapshot_hash", _snapshot_hash(self))

    @property
    def is_executable(self) -> bool:
        """Return whether all canonical execution axes are admitted."""
        return self.classification.status in {
            ExecutionClassificationStatus.EXPLICIT,
            ExecutionClassificationStatus.INFERRED,
        }

    def _validate_execution_axes(self) -> None:
        axes = (self.transport, self.interaction_mode, self.runtime_ownership)
        admitted = self.classification.status in {
            ExecutionClassificationStatus.EXPLICIT,
            ExecutionClassificationStatus.INFERRED,
        }
        if admitted:
            if not isinstance(self.transport, ExecutionTransport):
                raise ValueError("executable snapshot requires execution transport")
            if not isinstance(self.interaction_mode, InteractionMode):
                raise ValueError("executable snapshot requires interaction mode")
            if not isinstance(self.runtime_ownership, RuntimeOwnership):
                raise ValueError("executable snapshot requires runtime ownership")
            if (
                self.transport is ExecutionTransport.ONE_SHOT
                and self.interaction_mode is not InteractionMode.BATCH
            ):
                raise ValueError("one_shot execution must be batch")
            return
        if any(value is not None for value in axes):
            raise ValueError(
                "non-executable classification cannot retain canonical axes"
            )


def create_execution_snapshot(
    *,
    provider: ProviderRef,
    route: RouteRef,
    harness_id: str,
    harness_version: str,
    transport: ExecutionTransport,
    interaction_mode: InteractionMode,
    runtime_ownership: RuntimeOwnership,
    workspace_id: str,
    worktree_id: str | None,
    permission_profile: str,
    extension_snapshot_hash: str,
    budgets: ExecutionBudgets | None = None,
    compatibility_evidence: tuple[SnapshotEvidenceRef, ...] = (),
    capability_evidence: tuple[SnapshotEvidenceRef, ...] = (),
    classification: ExecutionClassification | None = None,
) -> ExecutionSnapshot:
    """Create a complete provider-neutral snapshot without Settings or gateway types."""
    return ExecutionSnapshot(
        provider=provider,
        route=route,
        harness_id=harness_id,
        harness_version=harness_version,
        transport=transport,
        interaction_mode=interaction_mode,
        runtime_ownership=runtime_ownership,
        workspace_id=workspace_id,
        worktree_id=worktree_id,
        permission_profile=permission_profile,
        extension_snapshot_hash=extension_snapshot_hash,
        budgets=budgets or ExecutionBudgets(),
        compatibility_evidence=compatibility_evidence,
        capability_evidence=capability_evidence,
        classification=classification
        or ExecutionClassification(
            status=ExecutionClassificationStatus.EXPLICIT,
            source="explicit_request",
        ),
    )


def execution_snapshot_to_dict(snapshot: ExecutionSnapshot) -> dict[str, Any]:
    """Serialize one snapshot using its forward-only canonical schema."""
    if not isinstance(snapshot, ExecutionSnapshot):
        raise ValueError("snapshot must be an ExecutionSnapshot")
    return {**_snapshot_payload(snapshot), "snapshot_hash": snapshot.snapshot_hash}


def execution_snapshot_from_dict(data: Mapping[str, Any]) -> ExecutionSnapshot:
    """Strictly parse and verify one canonical execution snapshot."""
    _require_mapping(data, field_name="execution snapshot")
    _reject_unknown_fields(
        data,
        {
            "schema_version",
            "provider",
            "route",
            "harness",
            "execution",
            "workspace",
            "permission_profile",
            "extension_snapshot_hash",
            "budgets",
            "evidence",
            "classification",
            "snapshot_hash",
        },
        field_name="execution snapshot",
    )
    schema_version = data.get("schema_version")
    if schema_version != EXECUTION_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported execution snapshot schema_version")
    supplied_hash = data.get("snapshot_hash")
    _validate_hash(supplied_hash, field_name="snapshot_hash")
    provider = _provider_ref_from_dict(data.get("provider"))
    route = _route_ref_from_dict(data.get("route"))
    harness = _strict_nested_mapping(
        data.get("harness"),
        allowed={"id", "version"},
        field_name="harness",
    )
    execution = _strict_nested_mapping(
        data.get("execution"),
        allowed={"transport", "interaction_mode", "runtime_ownership"},
        field_name="execution",
    )
    workspace = _strict_nested_mapping(
        data.get("workspace"),
        allowed={"id", "worktree_id"},
        field_name="workspace",
    )
    budgets = _budgets_from_dict(data.get("budgets"))
    evidence = _strict_nested_mapping(
        data.get("evidence"),
        allowed={"compatibility", "capability"},
        field_name="evidence",
    )
    classification = _classification_from_dict(data.get("classification"))
    snapshot = ExecutionSnapshot(
        provider=provider,
        route=route,
        harness_id=_required_text(harness.get("id"), field_name="harness id"),
        harness_version=_required_text(
            harness.get("version"),
            field_name="harness version",
        ),
        transport=_optional_enum(
            execution.get("transport"),
            ExecutionTransport,
            field_name="execution transport",
        ),
        interaction_mode=_optional_enum(
            execution.get("interaction_mode"),
            InteractionMode,
            field_name="interaction mode",
        ),
        runtime_ownership=_optional_enum(
            execution.get("runtime_ownership"),
            RuntimeOwnership,
            field_name="runtime ownership",
        ),
        workspace_id=_required_text(
            workspace.get("id"),
            field_name="workspace id",
        ),
        worktree_id=_optional_text(workspace.get("worktree_id")),
        permission_profile=_required_text(
            data.get("permission_profile"),
            field_name="permission profile",
        ),
        extension_snapshot_hash=_required_text(
            data.get("extension_snapshot_hash"),
            field_name="extension_snapshot_hash",
        ),
        budgets=budgets,
        compatibility_evidence=_evidence_refs_from_list(
            evidence.get("compatibility"),
            field_name="compatibility evidence",
        ),
        capability_evidence=_evidence_refs_from_list(
            evidence.get("capability"),
            field_name="capability evidence",
        ),
        classification=classification,
        schema_version=schema_version,
    )
    if snapshot.snapshot_hash != supplied_hash:
        raise ValueError("execution snapshot hash mismatch")
    return snapshot


def legacy_execution_placeholder(
    data: Mapping[str, Any],
    *,
    invocation_mode: str | None = None,
) -> ExecutionSnapshot:
    """Project one legacy snapshot as ambiguous without fabricating continuity."""
    _require_mapping(data, field_name="legacy execution snapshot")
    safe_identity = {
        "id": _optional_text(data.get("id")),
        "harness_id": _optional_text(data.get("harness_id")),
        "api_mode": _optional_text(data.get("api_mode")),
        "model": _optional_text(data.get("model")),
        "project_id": _optional_text(data.get("project_id")),
        "permission_mode": _optional_text(data.get("permission_mode")),
        "tool_config_hash": _optional_text(data.get("tool_config_hash")),
        "invocation_mode": _optional_text(invocation_mode),
    }
    fingerprint = _canonical_hash(safe_identity)
    provider = ProviderRef("legacy-unknown-provider", "unclassified")
    route = RouteRef(f"legacy-route-{fingerprint[:20]}", fingerprint, provider)
    harness_id = _safe_legacy_identity(
        data.get("harness_id"),
        fallback="legacy-unknown-harness",
    )
    workspace_id = _safe_legacy_identity(
        data.get("project_id"),
        fallback=f"legacy-workspace-{fingerprint[:20]}",
    )
    effective_workspace = _optional_text(data.get("effective_workspace"))
    source_workspace = _optional_text(data.get("source_workspace"))
    worktree_id = None
    if effective_workspace and effective_workspace != source_workspace:
        worktree_id = (
            "legacy-worktree-"
            + _canonical_hash({"effective_workspace": effective_workspace})[:20]
        )
    permission_profile = _safe_legacy_identity(
        data.get("permission_mode"),
        fallback="legacy-unknown-permission",
    )
    raw_extension_hash = _optional_text(data.get("tool_config_hash"))
    extension_hash = (
        raw_extension_hash.lower()
        if raw_extension_hash and _HASH_RE.fullmatch(raw_extension_hash.lower())
        else _canonical_hash({"legacy_tool_config_hash": raw_extension_hash})
    )
    return ExecutionSnapshot(
        provider=provider,
        route=route,
        harness_id=harness_id,
        harness_version="unknown",
        transport=None,
        interaction_mode=None,
        runtime_ownership=None,
        workspace_id=workspace_id,
        worktree_id=worktree_id,
        permission_profile=permission_profile,
        extension_snapshot_hash=extension_hash,
        compatibility_evidence=(
            SnapshotEvidenceRef(
                "legacy-snapshot",
                fingerprint,
                "ambiguous",
                "legacy-record",
            ),
        ),
        classification=ExecutionClassification(
            status=ExecutionClassificationStatus.AMBIGUOUS,
            source="legacy_record",
            reason_code="insufficient_execution_evidence",
            evidence=(f"legacy-{fingerprint[:20]}",),
        ),
    )


def _snapshot_hash(snapshot: ExecutionSnapshot) -> str:
    return _canonical_hash(_snapshot_payload(snapshot))


def _snapshot_payload(snapshot: ExecutionSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "provider": _provider_ref_to_dict(snapshot.provider),
        "route": _route_ref_to_dict(snapshot.route),
        "harness": {
            "id": snapshot.harness_id,
            "version": snapshot.harness_version,
        },
        "execution": {
            "transport": (
                snapshot.transport.value if snapshot.transport is not None else None
            ),
            "interaction_mode": (
                snapshot.interaction_mode.value
                if snapshot.interaction_mode is not None
                else None
            ),
            "runtime_ownership": (
                snapshot.runtime_ownership.value
                if snapshot.runtime_ownership is not None
                else None
            ),
        },
        "workspace": {
            "id": snapshot.workspace_id,
            "worktree_id": snapshot.worktree_id,
        },
        "permission_profile": snapshot.permission_profile,
        "extension_snapshot_hash": snapshot.extension_snapshot_hash,
        "budgets": _budgets_to_dict(snapshot.budgets),
        "evidence": {
            "compatibility": [
                _evidence_ref_to_dict(item) for item in snapshot.compatibility_evidence
            ],
            "capability": [
                _evidence_ref_to_dict(item) for item in snapshot.capability_evidence
            ],
        },
        "classification": _classification_to_dict(snapshot.classification),
    }


def _provider_ref_to_dict(reference: ProviderRef) -> dict[str, str]:
    return {"id": reference.id, "revision": reference.revision}


def _provider_ref_from_dict(data: Any) -> ProviderRef:
    mapping = _strict_nested_mapping(
        data,
        allowed={"id", "revision"},
        field_name="provider ref",
    )
    return ProviderRef(
        _required_text(mapping.get("id"), field_name="provider id"),
        _required_text(mapping.get("revision"), field_name="provider revision"),
    )


def _route_ref_to_dict(reference: RouteRef) -> dict[str, Any]:
    return {
        "id": reference.id,
        "revision": reference.revision,
        "provider": _provider_ref_to_dict(reference.provider),
    }


def _route_ref_from_dict(data: Any) -> RouteRef:
    mapping = _strict_nested_mapping(
        data,
        allowed={"id", "revision", "provider"},
        field_name="route ref",
    )
    return RouteRef(
        _required_text(mapping.get("id"), field_name="route id"),
        _required_text(mapping.get("revision"), field_name="route revision"),
        _provider_ref_from_dict(mapping.get("provider")),
    )


def _evidence_ref_to_dict(reference: SnapshotEvidenceRef) -> dict[str, str]:
    return {
        "id": reference.id,
        "revision": reference.revision,
        "status": reference.status,
        "source": reference.source,
    }


def _evidence_refs_from_list(
    data: Any,
    *,
    field_name: str,
) -> tuple[SnapshotEvidenceRef, ...]:
    if not isinstance(data, list):
        raise ValueError(f"{field_name} must be a list")
    items = []
    for raw in data:
        mapping = _strict_nested_mapping(
            raw,
            allowed={"id", "revision", "status", "source"},
            field_name="evidence ref",
        )
        items.append(
            SnapshotEvidenceRef(
                _required_text(mapping.get("id"), field_name="evidence id"),
                _required_text(
                    mapping.get("revision"),
                    field_name="evidence revision",
                ),
                _required_text(
                    mapping.get("status"),
                    field_name="evidence status",
                ),
                _required_text(
                    mapping.get("source"),
                    field_name="evidence source",
                ),
            )
        )
    return tuple(items)


def _normalize_evidence(
    items: tuple[SnapshotEvidenceRef, ...],
    *,
    field_name: str,
) -> tuple[SnapshotEvidenceRef, ...]:
    if not isinstance(items, tuple) or any(
        not isinstance(item, SnapshotEvidenceRef) for item in items
    ):
        raise ValueError(f"{field_name} evidence must be a tuple of refs")
    identifiers = [item.id for item in items]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"duplicate {field_name} evidence id")
    return tuple(sorted(items))


def _budgets_to_dict(budgets: ExecutionBudgets) -> dict[str, int | None]:
    return {
        "timeout_seconds": budgets.timeout_seconds,
        "retry_limit": budgets.retry_limit,
        "cost_limit_microunits": budgets.cost_limit_microunits,
        "token_limit": budgets.token_limit,
        "runtime_seconds": budgets.runtime_seconds,
    }


def _budgets_from_dict(data: Any) -> ExecutionBudgets:
    mapping = _strict_nested_mapping(
        data,
        allowed={
            "timeout_seconds",
            "retry_limit",
            "cost_limit_microunits",
            "token_limit",
            "runtime_seconds",
        },
        field_name="budgets",
    )
    return ExecutionBudgets(
        timeout_seconds=_optional_int(
            mapping.get("timeout_seconds"),
            field_name="timeout_seconds",
        ),
        retry_limit=_required_int(
            mapping.get("retry_limit"),
            field_name="retry_limit",
        ),
        cost_limit_microunits=_optional_int(
            mapping.get("cost_limit_microunits"),
            field_name="cost_limit_microunits",
        ),
        token_limit=_optional_int(
            mapping.get("token_limit"),
            field_name="token_limit",
        ),
        runtime_seconds=_optional_int(
            mapping.get("runtime_seconds"),
            field_name="runtime_seconds",
        ),
    )


def _classification_to_dict(
    classification: ExecutionClassification,
) -> dict[str, Any]:
    return {
        "status": classification.status.value,
        "source": classification.source,
        "reason_code": classification.reason_code,
        "evidence": list(classification.evidence),
    }


def _classification_from_dict(data: Any) -> ExecutionClassification:
    mapping = _strict_nested_mapping(
        data,
        allowed={"status", "source", "reason_code", "evidence"},
        field_name="classification",
    )
    raw_evidence = mapping.get("evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError("classification evidence must be a list")
    return ExecutionClassification(
        status=_required_enum(
            mapping.get("status"),
            ExecutionClassificationStatus,
            field_name="classification status",
        ),
        source=_required_text(
            mapping.get("source"),
            field_name="classification source",
        ),
        reason_code=_optional_text(mapping.get("reason_code")),
        evidence=tuple(
            _required_text(item, field_name="classification evidence")
            for item in raw_evidence
        ),
    )


def _strict_nested_mapping(
    data: Any,
    *,
    allowed: set[str],
    field_name: str,
) -> Mapping[str, Any]:
    _require_mapping(data, field_name=field_name)
    _reject_unknown_fields(data, allowed, field_name=field_name)
    return data


def _require_mapping(data: Any, *, field_name: str) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{field_name} must be an object")


def _reject_unknown_fields(
    data: Mapping[str, Any],
    allowed: set[str],
    *,
    field_name: str,
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown {field_name} fields: {', '.join(unknown)}")


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("text value must be a string")
    text = value.strip()
    return text or None


def _validate_identity(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")


def _safe_legacy_identity(value: Any, *, fallback: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if _IDENTITY_RE.fullmatch(text):
            return text
    return fallback


def _validate_hash(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 hash")


def _required_int(value: Any, *, field_name: str) -> int:
    _validate_non_negative_int(value, field_name=field_name)
    return value


def _optional_int(value: Any, *, field_name: str) -> int | None:
    _validate_optional_non_negative_int(value, field_name=field_name)
    return value


def _validate_non_negative_int(value: Any, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_optional_non_negative_int(value: Any, *, field_name: str) -> None:
    if value is not None:
        _validate_non_negative_int(value, field_name=field_name)


def _required_enum(value: Any, enum_type: type[Enum], *, field_name: str):
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    try:
        return enum_type(value)
    except ValueError:
        raise ValueError(f"{field_name} is invalid") from None


def _optional_enum(value: Any, enum_type: type[Enum], *, field_name: str):
    if value is None:
        return None
    return _required_enum(value, enum_type, field_name=field_name)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
