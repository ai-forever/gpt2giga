"""Versioned semantic-loss admission for the GigaLoom protocol bridge."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from enum import Enum
from types import MappingProxyType
from typing import Literal

from pydantic import Field

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
