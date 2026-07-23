"""Versioned product vocabulary and fail-closed capability admission."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping


PRODUCT_CAPABILITY_SCHEMA_VERSION = 1


class ProductCapabilityError(ValueError):
    """Raised when a product capability request is malformed or unknown."""


class TaskIntent(str, Enum):
    """Describe what outcome the operator wants."""

    ASK = "ask"
    REVIEW = "review"
    CHANGE = "change"


class AuthorityLevel(str, Enum):
    """Describe the maximum admitted workspace authority."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"


class TransportCapability(str, Enum):
    """Describe internal execution capabilities hidden from ordinary users."""

    STRUCTURED_SESSION = "structured_session"
    TERMINAL_SESSION = "terminal_session"
    ONE_SHOT = "one_shot"
    STREAMING_EVENTS = "streaming_events"


class ToolCapability(str, Enum):
    """Describe independently admitted tool authority."""

    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    PROCESS = "process"
    NETWORK = "network"
    GITHUB = "github"
    BROWSER = "browser"
    MCP = "mcp"
    CHILD_AGENT = "child_agent"


class TitleProvenance(str, Enum):
    """Describe the authoritative source of a session title."""

    UNTITLED = "untitled"
    LEGACY = "legacy"
    FALLBACK = "fallback"
    PROVIDER_NATIVE = "provider_native"
    MANUAL = "manual"


class IntegrationLifecycle(str, Enum):
    """Describe one integration definition and installed revision."""

    DEFINITION_ONLY = "definition_only"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"
    DEFINITION_DELETED = "definition_deleted"


class AdmissionStatus(str, Enum):
    """Describe the result of capability admission."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CapabilityRequest:
    """One versioned product request before provider route selection."""

    intent: TaskIntent
    authority: AuthorityLevel
    required_transports: frozenset[TransportCapability] = field(
        default_factory=frozenset
    )
    required_tools: frozenset[ToolCapability] = field(default_factory=frozenset)
    compatibility_notes: tuple[str, ...] = ()
    schema_version: int = PRODUCT_CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCT_CAPABILITY_SCHEMA_VERSION:
            raise ProductCapabilityError("unsupported product capability schema")
        if not isinstance(self.intent, TaskIntent):
            raise ProductCapabilityError("task intent is invalid")
        if not isinstance(self.authority, AuthorityLevel):
            raise ProductCapabilityError("authority level is invalid")
        transports = _enum_set(
            self.required_transports,
            TransportCapability,
            "transport capability",
        )
        tools = _enum_set(self.required_tools, ToolCapability, "tool capability")
        if (
            self.authority is AuthorityLevel.READ_ONLY
            and ToolCapability.FILESYSTEM_WRITE in tools
        ):
            raise ProductCapabilityError(
                "filesystem write requires workspace-write authority"
            )
        object.__setattr__(self, "required_transports", transports)
        object.__setattr__(self, "required_tools", tools)
        object.__setattr__(
            self,
            "compatibility_notes",
            tuple(sorted(set(self.compatibility_notes))),
        )


@dataclass(frozen=True)
class CapabilityAdmission:
    """A truthful, redaction-safe capability admission result."""

    status: AdmissionStatus
    why: tuple[str, ...]
    recovery: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = PRODUCT_CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCT_CAPABILITY_SCHEMA_VERSION:
            raise ProductCapabilityError("unsupported product capability schema")
        if not isinstance(self.status, AdmissionStatus):
            raise ProductCapabilityError("admission status is invalid")
        reasons = tuple(sorted(set(self.why)))
        if not reasons:
            raise ProductCapabilityError("admission requires a reason")
        object.__setattr__(self, "why", reasons)
        object.__setattr__(self, "recovery", tuple(sorted(set(self.recovery))))
        object.__setattr__(
            self,
            "diagnostics",
            MappingProxyType(dict(self.diagnostics)),
        )

    @property
    def available(self) -> bool:
        """Return whether every requested capability is admitted."""
        return self.status is AdmissionStatus.AVAILABLE

    @property
    def degraded(self) -> bool:
        """Return whether execution is possible with a visible downgrade."""
        return self.status is AdmissionStatus.DEGRADED

    @property
    def blocked(self) -> bool:
        """Return whether execution must fail before side effects."""
        return self.status is AdmissionStatus.BLOCKED

    def to_dict(self) -> dict[str, Any]:
        """Serialize the stable admission contract."""
        return {
            "schema_version": self.schema_version,
            "available": self.available,
            "degraded": self.degraded,
            "blocked": self.blocked,
            "why": list(self.why),
            "recovery": list(self.recovery),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class LegacyCapabilityMapping:
    """Document one compatibility alias without making it product vocabulary."""

    field: str
    value: str
    intent: TaskIntent | None = None
    authority: AuthorityLevel | None = None
    transport: TransportCapability | None = None
    note: str = ""


LEGACY_CAPABILITY_MAPPINGS = (
    LegacyCapabilityMapping(
        field="mode",
        value="plan",
        intent=TaskIntent.ASK,
        authority=AuthorityLevel.READ_ONLY,
        note="Compatibility alias; planning semantics remain visible during migration.",
    ),
    LegacyCapabilityMapping(
        field="mode",
        value="read",
        intent=TaskIntent.REVIEW,
        authority=AuthorityLevel.READ_ONLY,
        note="Compatibility alias for a read-only review request.",
    ),
    LegacyCapabilityMapping(
        field="mode",
        value="edit",
        intent=TaskIntent.CHANGE,
        authority=AuthorityLevel.WORKSPACE_WRITE,
        note="Compatibility alias for a workspace-changing request.",
    ),
    LegacyCapabilityMapping(
        field="execution_transport",
        value="native_structured",
        transport=TransportCapability.STRUCTURED_SESSION,
        note="Machine-only transport override; provider evidence still gates admission.",
    ),
    LegacyCapabilityMapping(
        field="execution_transport",
        value="native_terminal",
        transport=TransportCapability.TERMINAL_SESSION,
        note="Machine-only provider-terminal override.",
    ),
    LegacyCapabilityMapping(
        field="execution_transport",
        value="one_shot",
        transport=TransportCapability.ONE_SHOT,
        note="Machine-only compatibility execution override.",
    ),
    LegacyCapabilityMapping(
        field="invocation_mode",
        value="headless",
        note="Does not select a transport; route evidence must provide one.",
    ),
    LegacyCapabilityMapping(
        field="stream",
        value="true",
        transport=TransportCapability.STREAMING_EVENTS,
        note="Compatibility request; streaming is no longer an ordinary UI choice.",
    ),
    LegacyCapabilityMapping(
        field="stream",
        value="false",
        note="Compatibility opt-out; it does not select a transport.",
    ),
)
_LEGACY_BY_FIELD_VALUE = MappingProxyType(
    {(item.field, item.value): item for item in LEGACY_CAPABILITY_MAPPINGS}
)


def migrate_legacy_capability_request(
    payload: Mapping[str, Any],
) -> CapabilityRequest:
    """Map a legacy machine payload into product vocabulary without guessing."""
    mode = _legacy_mapping("mode", payload.get("mode", "plan"))
    intent = mode.intent
    authority = mode.authority
    if intent is None or authority is None:
        raise ProductCapabilityError("legacy mode has no product mapping")

    transports: set[TransportCapability] = set()
    notes = [mode.note]
    if "execution_transport" in payload:
        transport = _legacy_mapping(
            "execution_transport",
            payload["execution_transport"],
        )
        if transport.transport is None:
            raise ProductCapabilityError("legacy transport has no capability mapping")
        transports.add(transport.transport)
        notes.append(transport.note)
    if "invocation_mode" in payload:
        invocation = _legacy_mapping("invocation_mode", payload["invocation_mode"])
        notes.append(invocation.note)
        if (
            str(payload["invocation_mode"]).strip().lower() == "headless"
            and not transports
        ):
            raise ProductCapabilityError(
                "headless invocation does not prove an execution transport"
            )
    if "stream" in payload:
        stream_value = payload["stream"]
        if not isinstance(stream_value, bool):
            raise ProductCapabilityError("legacy stream value must be a boolean")
        stream = _legacy_mapping("stream", str(stream_value).lower())
        if stream.transport is not None:
            transports.add(stream.transport)
        notes.append(stream.note)

    return CapabilityRequest(
        intent=intent,
        authority=authority,
        required_transports=frozenset(transports),
        compatibility_notes=tuple(notes),
    )


def admit_capability_request(
    request: CapabilityRequest,
    *,
    available_transports: Iterable[TransportCapability],
    available_tools: Iterable[ToolCapability],
    degraded_transports: Iterable[TransportCapability] = (),
    degraded_tools: Iterable[ToolCapability] = (),
    diagnostics: Mapping[str, Any] | None = None,
) -> CapabilityAdmission:
    """Admit a request from explicit evidence and fail closed on missing proof."""
    available_transport_set = _enum_set(
        available_transports,
        TransportCapability,
        "transport capability",
    )
    available_tool_set = _enum_set(
        available_tools,
        ToolCapability,
        "tool capability",
    )
    degraded_transport_set = _enum_set(
        degraded_transports,
        TransportCapability,
        "transport capability",
    )
    degraded_tool_set = _enum_set(
        degraded_tools,
        ToolCapability,
        "tool capability",
    )
    missing_transports = request.required_transports - (
        available_transport_set | degraded_transport_set
    )
    missing_tools = request.required_tools - (available_tool_set | degraded_tool_set)
    if missing_transports or missing_tools:
        return CapabilityAdmission(
            status=AdmissionStatus.BLOCKED,
            why=tuple(
                f"transport_unavailable:{item.value}"
                for item in sorted(missing_transports, key=lambda item: item.value)
            )
            + tuple(
                f"tool_unavailable:{item.value}"
                for item in sorted(missing_tools, key=lambda item: item.value)
            ),
            recovery=("inspect_capability_diagnostics",),
            diagnostics=diagnostics or {},
        )
    degraded_requested_transports = request.required_transports & degraded_transport_set
    degraded_requested_tools = request.required_tools & degraded_tool_set
    if degraded_requested_transports or degraded_requested_tools:
        return CapabilityAdmission(
            status=AdmissionStatus.DEGRADED,
            why=tuple(
                f"transport_degraded:{item.value}"
                for item in sorted(
                    degraded_requested_transports,
                    key=lambda item: item.value,
                )
            )
            + tuple(
                f"tool_degraded:{item.value}"
                for item in sorted(
                    degraded_requested_tools,
                    key=lambda item: item.value,
                )
            ),
            recovery=("review_visible_downgrade",),
            diagnostics=diagnostics or {},
        )
    return CapabilityAdmission(
        status=AdmissionStatus.AVAILABLE,
        why=("capabilities_admitted",),
        diagnostics=diagnostics or {},
    )


def capability_manifest() -> dict[str, Any]:
    """Return the source-derived vocabulary manifest used by clients and docs."""
    return {
        "schema_version": PRODUCT_CAPABILITY_SCHEMA_VERSION,
        "task_intents": [item.value for item in TaskIntent],
        "authority_levels": [item.value for item in AuthorityLevel],
        "transport_capabilities": [item.value for item in TransportCapability],
        "tool_capabilities": [item.value for item in ToolCapability],
        "title_provenance": [item.value for item in TitleProvenance],
        "integration_lifecycle": [item.value for item in IntegrationLifecycle],
        "legacy_mappings": [
            {
                "field": item.field,
                "value": item.value,
                "intent": item.intent.value if item.intent is not None else None,
                "authority": (
                    item.authority.value if item.authority is not None else None
                ),
                "transport": (
                    item.transport.value if item.transport is not None else None
                ),
                "note": item.note,
            }
            for item in LEGACY_CAPABILITY_MAPPINGS
        ],
    }


def _legacy_mapping(field: str, value: Any) -> LegacyCapabilityMapping:
    normalized = str(value).strip().lower()
    try:
        return _LEGACY_BY_FIELD_VALUE[(field, normalized)]
    except KeyError as exc:
        raise ProductCapabilityError(
            f"unknown legacy capability value: {field}={normalized}"
        ) from exc


def _enum_set(values: Iterable[Any], enum_type: type[Enum], label: str) -> frozenset:
    normalized = frozenset(values)
    if not all(isinstance(item, enum_type) for item in normalized):
        raise ProductCapabilityError(f"{label} is invalid")
    return normalized
