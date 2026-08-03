"""Versioned semantic-loss admission for the GigaLoom protocol bridge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping
from copy import deepcopy
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypeVar

from pydantic import Field, model_validator

from gpt2giga.protocols.normalized.models import (
    NormalizedBaseModel,
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedTokenCountRequest,
    NormalizedTokenLimits,
)


class BridgeFeature(str, Enum):
    """Normalized v1 semantics that must survive the protocol bridge."""

    ROLES = "roles"
    ORDERED_CONTENT_PARTS = "ordered_content_parts"
    TEXT = "text"
    IMAGE_REFERENCES = "image_references"
    GENERATION_CONTROLS = "generation_controls"
    FUNCTION_TOOLS = "function_tools"
    TOOL_CHOICE = "tool_choice"
    PARALLEL_TOOL_CALLS = "parallel_tool_calls"
    TOOL_RESULTS = "tool_results"
    JSON_SCHEMA_OUTPUT = "json_schema_output"
    STREAM_DELTAS = "stream_deltas"
    STREAM_TERMINAL_EVENTS = "stream_terminal_events"
    STOP_REASON = "stop_reason"
    USAGE = "usage"
    MODEL_IDENTITY = "model_identity"
    REQUEST_ERROR_CLASSES = "request_error_classes"
    CANCELLATION = "cancellation"
    CONTEXT_TOKEN_LIMITS = "context_token_limits"
    COUNT_TOKENS = "count_tokens"


class DownstreamProtocol(str, Enum):
    """Downstream public wire protocols admitted by normalized v1."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class LossDisposition(str, Enum):
    """Whether one normalized feature can cross a downstream protocol."""

    EXACT = "exact"
    CONDITIONAL = "conditional"
    UNSUPPORTED = "unsupported"


class LossRule(NormalizedBaseModel):
    """Describe one versioned cell in the protocol loss matrix."""

    disposition: LossDisposition
    detail: str


class PublicProtocol(str, Enum):
    """Client-visible protocol identities covered by the 0.3 bridge."""

    OPENAI_RESPONSES = "openai_responses"
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"


class UpstreamProvider(str, Enum):
    """Reviewed upstream provider kinds covered by the 0.3 bridge."""

    GIGACHAT = "gigachat"
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class BridgeSupportStatus(str, Enum):
    """Release support status for one protocol/provider route."""

    STABLE = "stable"
    TECHNICAL_PREVIEW = "technical_preview"
    BLOCKED = "blocked"


class BridgeSemantic(str, Enum):
    """Required semantic rows in every public protocol/provider cell."""

    ROLES = "roles"
    MULTIMODAL_INPUTS = "multimodal_inputs"
    TOOL_DEFINITIONS_AND_CALL_IDS = "tool_definitions_and_call_ids"
    TOOL_CHOICE = "tool_choice"
    TOOL_RESULTS = "tool_results"
    PARALLEL_TOOL_CALLS = "parallel_tool_calls"
    STRUCTURED_OUTPUT_JSON_SCHEMA = "structured_output_json_schema"
    STREAM_LIFECYCLE = "stream_lifecycle"
    USAGE_INPUT_OUTPUT_TOKENS = "usage_input_output_tokens"
    USAGE_CACHE_TOKENS = "usage_cache_tokens"
    USAGE_REASONING_TOKENS = "usage_reasoning_tokens"
    STOP_REASONS = "stop_reasons"
    SAFETY_AND_REFUSAL = "safety_and_refusal"
    REASONING_CONTROLS_AND_SUMMARIES = "reasoning_controls_and_summaries"
    PREVIOUS_RESPONSE_STATE = "previous_response_state"
    FILES_AND_IMAGES = "files_and_images"
    HOSTED_AND_PROVIDER_NATIVE_TOOLS = "hosted_and_provider_native_tools"
    CANCELLATION = "cancellation"
    TIMEOUT = "timeout"
    MALFORMED_UPSTREAM_STREAM = "malformed_upstream_stream"
    DISCONNECT = "disconnect"


ReasonId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]
EvidenceId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$"),
]
MachineId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
]
PublicFieldPath = Annotated[
    str,
    Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.\[\]-]{0,127}$"),
]


class BridgeSemanticRule(NormalizedBaseModel):
    """Describe one semantic decision in a protocol/provider cell."""

    semantic: BridgeSemantic
    disposition: LossDisposition
    reason_id: ReasonId
    evidence_ids: tuple[EvidenceId, ...] = ()
    capability_predicate: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.:-]{2,127}$",
    )

    @model_validator(mode="after")
    def _validate_predicate(self) -> BridgeSemanticRule:
        if self.disposition is LossDisposition.CONDITIONAL:
            if self.capability_predicate is None:
                raise ValueError("conditional semantic rows require a predicate")
        elif self.capability_predicate is not None:
            raise ValueError("only conditional semantic rows may name a predicate")
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        return self


class BridgeLossCell(NormalizedBaseModel):
    """Describe one complete public protocol/upstream provider route."""

    public_protocol: PublicProtocol
    upstream_provider: UpstreamProvider
    status: BridgeSupportStatus
    reason_ids: tuple[ReasonId, ...] = Field(min_length=1)
    evidence_ids: tuple[EvidenceId, ...]
    client_version_window: str = Field(min_length=1)
    provider_version_window: str = Field(min_length=1)
    semantics: tuple[BridgeSemanticRule, ...]

    @model_validator(mode="after")
    def _validate_complete_cell(self) -> BridgeLossCell:
        semantics = tuple(sorted(self.semantics, key=lambda row: row.semantic.value))
        present = [row.semantic for row in semantics]
        if len(present) != len(set(present)):
            raise ValueError("semantic rows must be unique")
        missing = set(BridgeSemantic) - set(present)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"cell is missing semantic rows: {names}")
        if self.status is not BridgeSupportStatus.BLOCKED and not self.evidence_ids:
            raise ValueError("executable cells require evidence")
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "reason_ids", tuple(sorted(set(self.reason_ids))))
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        return self


class BridgeLossMatrix(NormalizedBaseModel):
    """Canonical, complete 4 by 4 bridge compatibility matrix."""

    schema_version: Literal["gpt2giga.bridge-loss-matrix.v1"] = (
        "gpt2giga.bridge-loss-matrix.v1"
    )
    cells: tuple[BridgeLossCell, ...]

    @model_validator(mode="after")
    def _validate_complete_matrix(self) -> BridgeLossMatrix:
        cells = tuple(
            sorted(
                self.cells,
                key=lambda cell: (
                    cell.public_protocol.value,
                    cell.upstream_provider.value,
                ),
            )
        )
        identities = [(cell.public_protocol, cell.upstream_provider) for cell in cells]
        if len(identities) != len(set(identities)):
            raise ValueError("protocol/provider cells must be unique")
        expected = {
            (protocol, provider)
            for protocol in PublicProtocol
            for provider in UpstreamProvider
        }
        missing = expected - set(identities)
        if missing:
            names = ", ".join(
                sorted(
                    f"{protocol.value}/{provider.value}"
                    for protocol, provider in missing
                )
            )
            raise ValueError(f"matrix is missing cells: {names}")
        object.__setattr__(self, "cells", cells)
        return self

    def canonical_payload(self) -> dict[str, Any]:
        """Return the secret-free content covered by the revision digest."""
        return _strip_extension_buckets(self.model_dump(mode="json"))

    def canonical_json(self) -> str:
        """Serialize deterministically for revision and machine projection."""
        return json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @property
    def revision(self) -> str:
        """Return the exact SHA-256 revision of canonical semantic content."""
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


class BridgeRequestedSemantic(NormalizedBaseModel):
    """Bind one content-free semantic requirement to its public field path."""

    semantic: BridgeSemantic
    public_field_path: PublicFieldPath


class _BridgeRouteIdentity(NormalizedBaseModel):
    public_alias: MachineId
    profile_id: MachineId
    config_revision: MachineId
    capability_profile_revision: MachineId


class BridgeAdmissionDecision(NormalizedBaseModel):
    """Record one exact route decision before provider dispatch."""

    schema_version: Literal["gpt2giga.bridge-admission.v1"] = (
        "gpt2giga.bridge-admission.v1"
    )
    public_protocol: PublicProtocol
    public_alias: MachineId
    upstream_provider: UpstreamProvider
    profile_id: MachineId
    config_revision: MachineId
    capability_profile_revision: MachineId
    loss_matrix_revision: MachineId
    support_status: BridgeSupportStatus
    requested_semantics: tuple[BridgeRequestedSemantic, ...]
    satisfied_capability_predicates: tuple[MachineId, ...]
    evidence_ids: tuple[EvidenceId, ...]


class BridgeMatrixAdmissionError(ValueError):
    """Stable fail-closed error raised before provider construction or I/O."""

    code = "unsupported_semantic"
    public_message = "The selected bridge route cannot preserve this semantic."

    def __init__(
        self,
        *,
        public_protocol: PublicProtocol,
        upstream_provider: UpstreamProvider,
        public_alias: str,
        public_field_path: str,
        reason_id: str,
    ) -> None:
        self.public_protocol = public_protocol
        self.upstream_provider = upstream_provider
        self.public_alias = public_alias
        self.public_field_path = public_field_path
        self.reason_id = reason_id
        super().__init__(
            f"{self.code}: {public_protocol.value}/{upstream_provider.value}: "
            f"{public_field_path}: {reason_id}"
        )

    def as_public_error(self) -> dict[str, str]:
        """Return the frozen OpenAI-shaped public rejection envelope."""
        return {
            "code": self.code,
            "message": self.public_message,
            "param": self.public_field_path,
            "type": "invalid_request_error",
        }


class NormalizedProtocolCapabilities(NormalizedBaseModel):
    """Declare reviewed capabilities for an upstream or adapter profile."""

    schema_version: Literal["gigaloom.protocol-capabilities.v1"] = (
        "gigaloom.protocol-capabilities.v1"
    )
    profile: str = Field(min_length=1)
    features: frozenset[BridgeFeature]
    limits: NormalizedTokenLimits | None = None


class ProtocolBridgeAdmission(NormalizedBaseModel):
    """Record a successful content-free bridge admission."""

    schema_version: Literal["gigaloom.protocol-bridge-admission.v1"] = (
        "gigaloom.protocol-bridge-admission.v1"
    )
    downstream: DownstreamProtocol
    upstream_profile: str
    required_features: tuple[BridgeFeature, ...]


class UnsupportedSemanticLossError(ValueError):
    """Raised before upstream traffic when normalized meaning would be lost."""

    def __init__(
        self,
        *,
        downstream: DownstreamProtocol,
        issues: Collection[str],
    ) -> None:
        self.downstream = downstream
        self.issues = tuple(sorted(set(issues)))
        joined = "; ".join(self.issues)
        super().__init__(
            f"Normalized v1 request is not admissible for {downstream.value}: {joined}"
        )


def _rule(disposition: LossDisposition, detail: str) -> LossRule:
    return LossRule(disposition=disposition, detail=detail)


_EXACT = {
    BridgeFeature.ROLES,
    BridgeFeature.ORDERED_CONTENT_PARTS,
    BridgeFeature.TEXT,
    BridgeFeature.FUNCTION_TOOLS,
    BridgeFeature.TOOL_CHOICE,
    BridgeFeature.TOOL_RESULTS,
    BridgeFeature.STREAM_DELTAS,
    BridgeFeature.STREAM_TERMINAL_EVENTS,
    BridgeFeature.STOP_REASON,
    BridgeFeature.USAGE,
    BridgeFeature.MODEL_IDENTITY,
    BridgeFeature.REQUEST_ERROR_CLASSES,
    BridgeFeature.CANCELLATION,
}
_CONDITIONAL = {
    BridgeFeature.IMAGE_REFERENCES,
    BridgeFeature.GENERATION_CONTROLS,
    BridgeFeature.JSON_SCHEMA_OUTPUT,
    BridgeFeature.CONTEXT_TOKEN_LIMITS,
}


def _base_rules() -> dict[BridgeFeature, LossRule]:
    rules = {
        feature: _rule(
            LossDisposition.EXACT,
            "Normalized v1 has a lossless downstream representation.",
        )
        for feature in _EXACT
    }
    rules.update(
        {
            feature: _rule(
                LossDisposition.CONDITIONAL,
                "Requires an explicit reviewed adapter or model capability.",
            )
            for feature in _CONDITIONAL
        }
    )
    return rules


def _build_loss_matrix() -> Mapping[
    DownstreamProtocol, Mapping[BridgeFeature, LossRule]
]:
    openai = _base_rules()
    openai[BridgeFeature.PARALLEL_TOOL_CALLS] = _rule(
        LossDisposition.EXACT,
        "OpenAI Chat Completions exposes parallel_tool_calls directly.",
    )
    openai[BridgeFeature.COUNT_TOKENS] = _rule(
        LossDisposition.UNSUPPORTED,
        "OpenAI Chat Completions has no normalized v1 count-tokens operation.",
    )

    anthropic = _base_rules()
    anthropic[BridgeFeature.PARALLEL_TOOL_CALLS] = _rule(
        LossDisposition.EXACT,
        "Anthropic tool choice exposes the parallel-use control.",
    )
    anthropic[BridgeFeature.COUNT_TOKENS] = _rule(
        LossDisposition.EXACT,
        "Anthropic Messages exposes count_tokens.",
    )

    gemini = _base_rules()
    gemini[BridgeFeature.TOOL_CHOICE] = _rule(
        LossDisposition.CONDITIONAL,
        "Named or required choice needs an exact function-calling mode mapping.",
    )
    gemini[BridgeFeature.PARALLEL_TOOL_CALLS] = _rule(
        LossDisposition.UNSUPPORTED,
        "Normalized v1 cannot preserve an explicit parallel-call toggle.",
    )
    gemini[BridgeFeature.COUNT_TOKENS] = _rule(
        LossDisposition.EXACT,
        "Gemini GenerateContent exposes countTokens.",
    )

    matrix = {
        DownstreamProtocol.OPENAI: MappingProxyType(openai),
        DownstreamProtocol.ANTHROPIC: MappingProxyType(anthropic),
        DownstreamProtocol.GEMINI: MappingProxyType(gemini),
    }
    expected = set(BridgeFeature)
    for downstream, rules in matrix.items():
        missing = expected - set(rules)
        if missing:
            names = ", ".join(sorted(feature.value for feature in missing))
            raise RuntimeError(f"Incomplete {downstream.value} loss matrix: {names}")
    return MappingProxyType(matrix)


PROTOCOL_LOSS_MATRIX_V1 = _build_loss_matrix()
PROTOCOL_LOSS_MATRIX_SCHEMA_VERSION = "gigaloom.protocol-loss-matrix.v1"


def protocol_loss_matrix_json() -> dict[str, object]:
    """Return the complete matrix as a stable JSON-serializable document."""
    return {
        "schema_version": PROTOCOL_LOSS_MATRIX_SCHEMA_VERSION,
        "upstream": "openai_compatible",
        "implementation_status": "openai_compatible_upstream_adapter",
        "downstreams": {
            downstream.value: {
                feature.value: rule.model_dump(
                    mode="json",
                    exclude={"raw_extensions", "provider_metadata"},
                )
                for feature, rule in sorted(
                    rules.items(), key=lambda item: item[0].value
                )
            }
            for downstream, rules in PROTOCOL_LOSS_MATRIX_V1.items()
        },
    }


_PREVIEW_EXACT_SEMANTICS = {
    BridgeSemantic.ROLES,
    BridgeSemantic.TOOL_DEFINITIONS_AND_CALL_IDS,
    BridgeSemantic.TOOL_CHOICE,
    BridgeSemantic.TOOL_RESULTS,
    BridgeSemantic.STREAM_LIFECYCLE,
    BridgeSemantic.USAGE_INPUT_OUTPUT_TOKENS,
    BridgeSemantic.STOP_REASONS,
    BridgeSemantic.CANCELLATION,
    BridgeSemantic.TIMEOUT,
    BridgeSemantic.MALFORMED_UPSTREAM_STREAM,
    BridgeSemantic.DISCONNECT,
}
_PREVIEW_CONDITIONAL_SEMANTICS = {
    BridgeSemantic.MULTIMODAL_INPUTS,
    BridgeSemantic.PARALLEL_TOOL_CALLS,
    BridgeSemantic.STRUCTURED_OUTPUT_JSON_SCHEMA,
    BridgeSemantic.SAFETY_AND_REFUSAL,
    BridgeSemantic.FILES_AND_IMAGES,
}


def _cell_semantics(
    *,
    status: BridgeSupportStatus,
    evidence_ids: tuple[str, ...],
    conditional_semantics: Collection[BridgeSemantic] = (),
) -> tuple[BridgeSemanticRule, ...]:
    if status is BridgeSupportStatus.BLOCKED:
        return tuple(
            BridgeSemanticRule(
                semantic=semantic,
                disposition=LossDisposition.UNSUPPORTED,
                reason_id="route_not_integrated",
            )
            for semantic in BridgeSemantic
        )

    rows: list[BridgeSemanticRule] = []
    for semantic in BridgeSemantic:
        if semantic in _PREVIEW_EXACT_SEMANTICS:
            rows.append(
                BridgeSemanticRule(
                    semantic=semantic,
                    disposition=LossDisposition.EXACT,
                    reason_id="hermetic_facade_evidence",
                    evidence_ids=evidence_ids,
                )
            )
        elif semantic in _PREVIEW_CONDITIONAL_SEMANTICS or semantic in (
            conditional_semantics
        ):
            rows.append(
                BridgeSemanticRule(
                    semantic=semantic,
                    disposition=LossDisposition.CONDITIONAL,
                    reason_id="requires_reviewed_capability",
                    evidence_ids=evidence_ids,
                    capability_predicate=f"capability.{semantic.value}",
                )
            )
        else:
            rows.append(
                BridgeSemanticRule(
                    semantic=semantic,
                    disposition=LossDisposition.UNSUPPORTED,
                    reason_id="semantic_not_proven",
                )
            )
    return tuple(rows)


def _client_version_window(protocol: PublicProtocol) -> str:
    return {
        PublicProtocol.OPENAI_RESPONSES: "codex-cli==0.146.0;openai-python==2.50.0",
        PublicProtocol.OPENAI_CHAT_COMPLETIONS: "openai-python==2.50.0",
        PublicProtocol.ANTHROPIC_MESSAGES: (
            "claude-code==2.1.212;anthropic-python==0.120.2"
        ),
        PublicProtocol.GEMINI_GENERATE_CONTENT: "google-genai-python==2.14.0",
    }[protocol]


def _build_bridge_loss_matrix() -> BridgeLossMatrix:
    cells: list[BridgeLossCell] = []
    for protocol in PublicProtocol:
        for provider in UpstreamProvider:
            if provider is UpstreamProvider.GIGACHAT:
                status = (
                    BridgeSupportStatus.STABLE
                    if protocol is PublicProtocol.OPENAI_CHAT_COMPLETIONS
                    else BridgeSupportStatus.TECHNICAL_PREVIEW
                )
                reason_ids = {
                    PublicProtocol.OPENAI_CHAT_COMPLETIONS: (
                        "baseline_gigachat_chat_conformance",
                    ),
                    PublicProtocol.OPENAI_RESPONSES: (
                        "normalized_responses_parity_incomplete",
                    ),
                    PublicProtocol.ANTHROPIC_MESSAGES: ("cross_protocol_route",),
                    PublicProtocol.GEMINI_GENERATE_CONTENT: ("cross_protocol_route",),
                }[protocol]
                evidence_ids = {
                    PublicProtocol.OPENAI_CHAT_COMPLETIONS: ("P0-BASELINE-2026-08-03",),
                    PublicProtocol.OPENAI_RESPONSES: (
                        "COR-01-CODEX-RESPONSES-2026-08-03",
                    ),
                    PublicProtocol.ANTHROPIC_MESSAGES: (
                        "COR-02-CLAUDE-MESSAGES-2026-08-03",
                    ),
                    PublicProtocol.GEMINI_GENERATE_CONTENT: (
                        "COR-03-GEMINI-CONTENT-2026-08-03",
                    ),
                }[protocol]
                provider_window = "gigachat-python>=0.2.3,<0.3.0"
            else:
                status = BridgeSupportStatus.BLOCKED
                reason_ids = ("route_not_integrated",)
                evidence_ids = ()
                provider_window = "not-integrated"
            cells.append(
                BridgeLossCell(
                    public_protocol=protocol,
                    upstream_provider=provider,
                    status=status,
                    reason_ids=reason_ids,
                    evidence_ids=evidence_ids,
                    client_version_window=_client_version_window(protocol),
                    provider_version_window=provider_window,
                    semantics=_cell_semantics(
                        status=status,
                        evidence_ids=evidence_ids,
                        conditional_semantics=(
                            (BridgeSemantic.HOSTED_AND_PROVIDER_NATIVE_TOOLS,)
                            if provider is UpstreamProvider.GIGACHAT
                            and protocol is PublicProtocol.OPENAI_RESPONSES
                            else ()
                        ),
                    ),
                )
            )
    return BridgeLossMatrix(cells=tuple(cells))


def _strip_extension_buckets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_extension_buckets(item)
            for key, item in value.items()
            if key not in {"provider_metadata", "raw_extensions"}
        }
    if isinstance(value, list):
        return [_strip_extension_buckets(item) for item in value]
    return value


BRIDGE_LOSS_MATRIX_V1 = _build_bridge_loss_matrix()
BRIDGE_LOSS_MATRIX_SCHEMA_VERSION = "gpt2giga.bridge-loss-matrix.v1"
_BRIDGE_LOSS_MATRIX_REVISION = BRIDGE_LOSS_MATRIX_V1.revision
_BRIDGE_LOSS_MATRIX_PAYLOAD = BRIDGE_LOSS_MATRIX_V1.canonical_payload()
_BRIDGE_LOSS_CELLS = MappingProxyType(
    {
        (cell.public_protocol, cell.upstream_provider): cell
        for cell in BRIDGE_LOSS_MATRIX_V1.cells
    }
)
_BRIDGE_LOSS_RULES = MappingProxyType(
    {
        identity: MappingProxyType({row.semantic: row for row in cell.semantics})
        for identity, cell in _BRIDGE_LOSS_CELLS.items()
    }
)


def bridge_loss_matrix_json() -> dict[str, Any]:
    """Return the canonical complete matrix with its exact revision digest."""
    payload = deepcopy(_BRIDGE_LOSS_MATRIX_PAYLOAD)
    payload["matrix_revision"] = _BRIDGE_LOSS_MATRIX_REVISION
    return payload


def admit_bridge_route(
    *,
    public_protocol: PublicProtocol,
    public_alias: str,
    upstream_provider: UpstreamProvider,
    profile_id: str,
    config_revision: str,
    capability_profile_revision: str,
    requested_semantics: Mapping[BridgeSemantic, str],
    capability_predicates: Collection[str] = (),
    capability_predicate_reasons: Mapping[str, str] | None = None,
    matrix: BridgeLossMatrix = BRIDGE_LOSS_MATRIX_V1,
) -> BridgeAdmissionDecision:
    """Admit one exact route without constructing a provider client."""
    identity = _BridgeRouteIdentity(
        public_alias=public_alias,
        profile_id=profile_id,
        config_revision=config_revision,
        capability_profile_revision=capability_profile_revision,
    )
    identity_key = (public_protocol, upstream_provider)
    if matrix is BRIDGE_LOSS_MATRIX_V1:
        cell = _BRIDGE_LOSS_CELLS[identity_key]
        rules = _BRIDGE_LOSS_RULES[identity_key]
        matrix_revision = _BRIDGE_LOSS_MATRIX_REVISION
    else:
        cell = next(
            cell
            for cell in matrix.cells
            if cell.public_protocol is public_protocol
            and cell.upstream_provider is upstream_provider
        )
        rules = {row.semantic: row for row in cell.semantics}
        matrix_revision = matrix.revision
    if cell.status is BridgeSupportStatus.BLOCKED:
        raise BridgeMatrixAdmissionError(
            public_protocol=public_protocol,
            upstream_provider=upstream_provider,
            public_alias=identity.public_alias,
            public_field_path="model",
            reason_id=cell.reason_ids[0],
        )

    requested = tuple(
        BridgeRequestedSemantic(
            semantic=semantic,
            public_field_path=public_field_path,
        )
        for semantic, public_field_path in sorted(
            requested_semantics.items(),
            key=lambda item: item[0].value,
        )
    )
    predicates = frozenset(capability_predicates)
    satisfied: set[str] = set()
    evidence = set(cell.evidence_ids)
    for item in requested:
        rule = rules[item.semantic]
        if rule.disposition is LossDisposition.UNSUPPORTED:
            raise BridgeMatrixAdmissionError(
                public_protocol=public_protocol,
                upstream_provider=upstream_provider,
                public_alias=identity.public_alias,
                public_field_path=item.public_field_path,
                reason_id=rule.reason_id,
            )
        if rule.disposition is LossDisposition.CONDITIONAL:
            predicate = rule.capability_predicate
            if predicate is None or predicate not in predicates:
                predicate_reasons = capability_predicate_reasons or {}
                raise BridgeMatrixAdmissionError(
                    public_protocol=public_protocol,
                    upstream_provider=upstream_provider,
                    public_alias=identity.public_alias,
                    public_field_path=item.public_field_path,
                    reason_id=predicate_reasons.get(predicate or "", rule.reason_id),
                )
            satisfied.add(predicate)
        evidence.update(rule.evidence_ids)

    return BridgeAdmissionDecision(
        public_protocol=public_protocol,
        public_alias=identity.public_alias,
        upstream_provider=upstream_provider,
        profile_id=identity.profile_id,
        config_revision=identity.config_revision,
        capability_profile_revision=identity.capability_profile_revision,
        loss_matrix_revision=matrix_revision,
        support_status=cell.status,
        requested_semantics=requested,
        satisfied_capability_predicates=tuple(sorted(satisfied)),
        evidence_ids=tuple(sorted(evidence)),
    )


_DispatchResult = TypeVar("_DispatchResult")


async def admit_then_dispatch_bridge_route(
    *,
    dispatch: Callable[[BridgeAdmissionDecision], Awaitable[_DispatchResult]],
    public_protocol: PublicProtocol,
    public_alias: str,
    upstream_provider: UpstreamProvider,
    profile_id: str,
    config_revision: str,
    capability_profile_revision: str,
    requested_semantics: Mapping[BridgeSemantic, str],
    capability_predicates: Collection[str] = (),
    capability_predicate_reasons: Mapping[str, str] | None = None,
    matrix: BridgeLossMatrix = BRIDGE_LOSS_MATRIX_V1,
) -> _DispatchResult:
    """Run fail-closed matrix admission before exact provider dispatch."""
    decision = admit_bridge_route(
        public_protocol=public_protocol,
        public_alias=public_alias,
        upstream_provider=upstream_provider,
        profile_id=profile_id,
        config_revision=config_revision,
        capability_profile_revision=capability_profile_revision,
        requested_semantics=requested_semantics,
        capability_predicates=capability_predicates,
        capability_predicate_reasons=capability_predicate_reasons,
        matrix=matrix,
    )
    return await dispatch(decision)


def admit_protocol_bridge_request(
    request: NormalizedChatRequest | NormalizedTokenCountRequest,
    *,
    downstream: DownstreamProtocol,
    upstream: NormalizedProtocolCapabilities,
    downstream_capabilities: Collection[BridgeFeature] = (),
    input_token_count: int | None = None,
) -> ProtocolBridgeAdmission:
    """Admit normalized v1 meaning before an adapter may perform upstream I/O."""
    chat_request = (
        request.input if isinstance(request, NormalizedTokenCountRequest) else request
    )
    issues: list[str] = []
    if isinstance(request, NormalizedTokenCountRequest):
        _reject_extensions(request, path="request", issues=issues)
    required = _required_features(chat_request, issues=issues)
    if isinstance(request, NormalizedTokenCountRequest):
        required.add(BridgeFeature.COUNT_TOKENS)

    missing_upstream = required - set(upstream.features)
    issues.extend(
        f"upstream profile {upstream.profile!r} lacks {feature.value}"
        for feature in sorted(missing_upstream, key=lambda item: item.value)
    )

    target_features = set(downstream_capabilities)
    for feature in sorted(required, key=lambda item: item.value):
        rule = PROTOCOL_LOSS_MATRIX_V1[downstream][feature]
        if rule.disposition is LossDisposition.UNSUPPORTED:
            issues.append(f"{feature.value} is unsupported: {rule.detail}")
        elif (
            rule.disposition is LossDisposition.CONDITIONAL
            and feature not in target_features
        ):
            issues.append(f"{feature.value} is conditional: {rule.detail}")

    _validate_limits(
        chat_request,
        capabilities=upstream,
        input_token_count=input_token_count,
        issues=issues,
    )
    if issues:
        raise UnsupportedSemanticLossError(
            downstream=downstream,
            issues=issues,
        )
    return ProtocolBridgeAdmission(
        downstream=downstream,
        upstream_profile=upstream.profile,
        required_features=tuple(sorted(required, key=lambda item: item.value)),
    )


def _required_features(
    request: NormalizedChatRequest,
    *,
    issues: list[str],
) -> set[BridgeFeature]:
    required = {
        BridgeFeature.ROLES,
        BridgeFeature.ORDERED_CONTENT_PARTS,
        BridgeFeature.STOP_REASON,
        BridgeFeature.USAGE,
        BridgeFeature.MODEL_IDENTITY,
        BridgeFeature.REQUEST_ERROR_CLASSES,
        BridgeFeature.CANCELLATION,
        BridgeFeature.CONTEXT_TOKEN_LIMITS,
    }
    _reject_extensions(request, path="request", issues=issues)
    _reject_extensions(
        request.generation_config,
        path="generation_config",
        issues=issues,
    )
    generation_values = request.generation_config.model_dump(
        exclude={"raw_extensions", "provider_metadata"},
    )
    if any(value is not None for value in generation_values.values()):
        required.add(BridgeFeature.GENERATION_CONTROLS)
    if request.cancellation is not None:
        _reject_extensions(request.cancellation, path="cancellation", issues=issues)
    for index, message in enumerate(request.messages):
        path = f"messages[{index}]"
        if message.role not in {"system", "user", "assistant", "tool"}:
            issues.append(f"{path}.role {message.role!r} is outside normalized v1")
        _reject_extensions(message, path=path, issues=issues)
        if message.role == "tool":
            required.add(BridgeFeature.TOOL_RESULTS)
            if not message.tool_call_id:
                issues.append(f"{path}.tool_call_id is required for a tool result")
            if message.tool_calls:
                issues.append(
                    f"{path} cannot contain both a tool result and tool calls"
                )
        elif message.tool_call_id is not None:
            issues.append(f"{path}.tool_call_id is only valid for a tool result")
        if message.tool_calls and message.role != "assistant":
            issues.append(f"{path}.tool_calls require the assistant role")
        if isinstance(message.content, str):
            required.add(BridgeFeature.TEXT)
        elif isinstance(message.content, list):
            for part_index, part in enumerate(message.content):
                _classify_content_part(
                    part,
                    path=f"{path}.content[{part_index}]",
                    role=message.role,
                    required=required,
                    issues=issues,
                )
        for call_index, tool_call in enumerate(message.tool_calls):
            required.add(BridgeFeature.FUNCTION_TOOLS)
            _reject_extensions(
                tool_call,
                path=f"{path}.tool_calls[{call_index}]",
                issues=issues,
            )
            if tool_call.type != "function" or not tool_call.name:
                issues.append(
                    f"{path}.tool_calls[{call_index}] is not a named function call"
                )

    for index, tool in enumerate(request.tools):
        required.add(BridgeFeature.FUNCTION_TOOLS)
        _reject_extensions(tool, path=f"tools[{index}]", issues=issues)
        if tool.type != "function" or not tool.name:
            issues.append(f"tools[{index}] is not a named function tool")

    if request.tool_choice is not None:
        required.add(BridgeFeature.TOOL_CHOICE)
        if not _is_admitted_tool_choice(request.tool_choice):
            issues.append("tool_choice is outside normalized v1")
    if request.parallel_tool_calls is not None:
        required.add(BridgeFeature.PARALLEL_TOOL_CALLS)
    if request.response_format is not None:
        _reject_extensions(
            request.response_format, path="response_format", issues=issues
        )
        if (
            request.response_format.type != "json_schema"
            or not request.response_format.json_schema
        ):
            issues.append("response_format must contain a normalized JSON schema")
        else:
            required.add(BridgeFeature.JSON_SCHEMA_OUTPUT)
    if request.stream:
        required.update(
            {
                BridgeFeature.STREAM_DELTAS,
                BridgeFeature.STREAM_TERMINAL_EVENTS,
            }
        )
    return required


def _classify_content_part(
    part: NormalizedContentPart,
    *,
    path: str,
    role: str,
    required: set[BridgeFeature],
    issues: list[str],
) -> None:
    _reject_extensions(part, path=path, issues=issues)
    if part.type == "text" and part.text is not None:
        if part.image_reference is not None or part.data is not None:
            issues.append(f"{path} mixes text with another content representation")
        required.add(BridgeFeature.TEXT)
        return
    if part.type == "image_reference" and part.image_reference is not None:
        _reject_extensions(
            part.image_reference,
            path=f"{path}.image_reference",
            issues=issues,
        )
        if part.text is not None or part.data is not None:
            issues.append(f"{path} mixes an image with another content representation")
        if role != "user":
            issues.append(f"{path} image references require the user role")
        required.add(BridgeFeature.IMAGE_REFERENCES)
        return
    issues.append(f"{path}.type {part.type!r} is outside normalized v1")


def _reject_extensions(
    value: NormalizedBaseModel,
    *,
    path: str,
    issues: list[str],
) -> None:
    if value.raw_extensions:
        issues.append(f"{path}.raw_extensions contain unmodeled semantics")
    if value.provider_metadata:
        issues.append(f"{path}.provider_metadata is not admitted on bridge input")


def _is_admitted_tool_choice(value: object) -> bool:
    if isinstance(value, str) and value in {"none", "auto", "required"}:
        return True
    if not isinstance(value, Mapping):
        return False
    if value.get("type") != "function":
        return False
    function = value.get("function")
    return isinstance(function, Mapping) and isinstance(function.get("name"), str)


def _validate_limits(
    request: NormalizedChatRequest,
    *,
    capabilities: NormalizedProtocolCapabilities,
    input_token_count: int | None,
    issues: list[str],
) -> None:
    limits = capabilities.limits
    if limits is None or limits.context_window is None:
        issues.append(
            f"upstream profile {capabilities.profile!r} lacks a context window"
        )
        return
    if input_token_count is not None and input_token_count < 0:
        issues.append("input_token_count must be non-negative")
        return
    if (
        input_token_count is not None
        and limits.max_input_tokens is not None
        and input_token_count > limits.max_input_tokens
    ):
        issues.append("input token count exceeds the upstream input limit")
    max_output = request.generation_config.max_tokens
    if (
        max_output is not None
        and limits.max_output_tokens is not None
        and max_output > limits.max_output_tokens
    ):
        issues.append("requested output tokens exceed the upstream output limit")
    if (
        input_token_count is not None
        and max_output is not None
        and input_token_count + max_output > limits.context_window
    ):
        issues.append("input plus requested output exceeds the context window")
