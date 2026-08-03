"""Bind selected-model capability decisions to bridge admission predicates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from gpt2giga.capabilities.models import (
    CAPABILITY_KEYS_V1,
    CapabilityKey,
    CapabilityScope,
    CapabilitySource,
    CapabilityState,
    EffectiveModelCapabilities,
)
from gpt2giga.capabilities.overlays import resolve_gigachat_model_layer
from gpt2giga.capabilities.resolver import (
    EffectiveCapabilityResolver,
    build_capability_layer,
)
from gpt2giga.protocols.normalized.loss_matrix import BridgeSemantic


_ADAPTER_STATES = MappingProxyType(
    {
        CapabilityKey.TEXT_INPUT: CapabilityState.SUPPORTED,
        CapabilityKey.STREAMING: CapabilityState.SUPPORTED,
        CapabilityKey.FUNCTION_TOOLS: CapabilityState.SUPPORTED,
        CapabilityKey.HOSTED_WEB_SEARCH: CapabilityState.SUPPORTED,
        CapabilityKey.HOSTED_URL_EXTRACTION: CapabilityState.SUPPORTED,
        CapabilityKey.HOSTED_CODE_INTERPRETER: CapabilityState.SUPPORTED,
        CapabilityKey.HOSTED_IMAGE_GENERATION: CapabilityState.SUPPORTED,
        CapabilityKey.HOSTED_3D_GENERATION: CapabilityState.SUPPORTED,
        CapabilityKey.PARALLEL_TOOL_CALLS: CapabilityState.UNSUPPORTED,
        CapabilityKey.JSON_SCHEMA_OUTPUT: CapabilityState.SUPPORTED,
        CapabilityKey.REASONING_CONTROLS: CapabilityState.UNSUPPORTED,
        CapabilityKey.REASONING_SUMMARY: CapabilityState.UNSUPPORTED,
        CapabilityKey.PREVIOUS_RESPONSE_STATE: CapabilityState.UNSUPPORTED,
        CapabilityKey.CONVERSATION_STATE: CapabilityState.UNSUPPORTED,
        CapabilityKey.FILE_INPUT: CapabilityState.SUPPORTED,
        CapabilityKey.IMAGE_INPUT: CapabilityState.SUPPORTED,
        CapabilityKey.USAGE_TOKENS: CapabilityState.SUPPORTED,
        CapabilityKey.CANCELLATION: CapabilityState.SUPPORTED,
        CapabilityKey.DISCONNECT: CapabilityState.SUPPORTED,
    }
)
_V1_UNSUPPORTED = frozenset(
    {
        CapabilityKey.HOSTED_WEB_SEARCH,
        CapabilityKey.HOSTED_URL_EXTRACTION,
        CapabilityKey.HOSTED_CODE_INTERPRETER,
        CapabilityKey.HOSTED_IMAGE_GENERATION,
        CapabilityKey.HOSTED_3D_GENERATION,
        CapabilityKey.PREVIOUS_RESPONSE_STATE,
        CapabilityKey.CONVERSATION_STATE,
    }
)
_HOSTED_TOOLS = frozenset(
    {
        CapabilityKey.HOSTED_WEB_SEARCH,
        CapabilityKey.HOSTED_URL_EXTRACTION,
        CapabilityKey.HOSTED_CODE_INTERPRETER,
        CapabilityKey.HOSTED_IMAGE_GENERATION,
        CapabilityKey.HOSTED_3D_GENERATION,
    }
)
_SEMANTIC_CAPABILITIES = MappingProxyType(
    {
        BridgeSemantic.MULTIMODAL_INPUTS: (CapabilityKey.IMAGE_INPUT,),
        BridgeSemantic.PARALLEL_TOOL_CALLS: (CapabilityKey.PARALLEL_TOOL_CALLS,),
        BridgeSemantic.STRUCTURED_OUTPUT_JSON_SCHEMA: (
            CapabilityKey.JSON_SCHEMA_OUTPUT,
        ),
        BridgeSemantic.FILES_AND_IMAGES: (
            CapabilityKey.FILE_INPUT,
            CapabilityKey.IMAGE_INPUT,
        ),
    }
)


@dataclass(frozen=True)
class CapabilityPredicateAdmission:
    """Supported predicates and exact reasons for unsatisfied predicates."""

    supported: frozenset[str]
    failure_reasons: Mapping[str, str]
    capability_revision: str


def resolve_gigachat_route_capabilities(
    *,
    model_id: str,
    public_protocol: str,
    api_mode: Literal["v1", "v2"],
    route_id: str,
    builtin_tools_enabled: bool = True,
) -> EffectiveModelCapabilities:
    """Resolve current normalized GigaChat adapter capabilities for one route."""
    protocol_layer = build_capability_layer(
        scope=CapabilityScope.PUBLIC_PROTOCOL,
        scope_id=public_protocol,
        source=CapabilitySource.PUBLIC_PROTOCOL,
        default_state=CapabilityState.SUPPORTED,
        evidence_ids=("OPENAI-RESPONSES-SEMANTICS-2026-08-03",),
    )
    adapter_states = dict(_ADAPTER_STATES)
    if not builtin_tools_enabled:
        adapter_states.update(
            {key: CapabilityState.UNSUPPORTED for key in _HOSTED_TOOLS}
        )
    adapter_layer = build_capability_layer(
        scope=CapabilityScope.PROVIDER_ADAPTER,
        scope_id="gigachat-normalized-v1",
        source=CapabilitySource.PROVIDER_ADAPTER,
        states=adapter_states,
        evidence_ids=("GIGACHAT-NORMALIZED-ADAPTER-2026-08-03",),
    )
    model_layer = resolve_gigachat_model_layer(model_id, api_mode)
    api_states = {
        key: (
            CapabilityState.UNSUPPORTED
            if api_mode == "v1" and key in _V1_UNSUPPORTED
            else CapabilityState.SUPPORTED
        )
        for key in CAPABILITY_KEYS_V1
    }
    api_layer = build_capability_layer(
        scope=CapabilityScope.API_MODE,
        scope_id=api_mode,
        source=CapabilitySource.API_MODE,
        states=api_states,
        evidence_ids=(f"GIGACHAT-{api_mode.upper()}-MODE-2026-08-03",),
    )
    route_layer = build_capability_layer(
        scope=CapabilityScope.ROUTE_POLICY,
        scope_id=route_id,
        source=CapabilitySource.ROUTE_POLICY,
        default_state=CapabilityState.SUPPORTED,
        evidence_ids=("IMMUTABLE-ROUTE-POLICY-2026-08-03",),
    )
    return EffectiveCapabilityResolver().resolve(
        model_id=model_id,
        provider_kind="gigachat",
        public_protocol=public_protocol,
        api_mode=api_mode,
        public_protocol_layer=protocol_layer,
        provider_adapter_layer=adapter_layer,
        model_layer=model_layer,
        api_mode_layer=api_layer,
        route_policy_layer=route_layer,
    )


def capability_predicates_for_semantics(
    effective: EffectiveModelCapabilities,
    requested_semantics: Mapping[BridgeSemantic, str],
    *,
    capability_requirements: Mapping[BridgeSemantic, tuple[CapabilityKey, ...]]
    | None = None,
) -> CapabilityPredicateAdmission:
    """Translate exact effective decisions into loss-matrix predicates."""
    supported: set[str] = set()
    failures: dict[str, str] = {}
    for semantic in requested_semantics:
        if capability_requirements is not None and semantic in capability_requirements:
            capability_keys = capability_requirements[semantic]
        else:
            capability_keys = _SEMANTIC_CAPABILITIES.get(semantic)
        if capability_keys is None:
            continue
        predicate = f"capability.{semantic.value}"
        if not capability_keys:
            failures[predicate] = "unsupported_hosted_tool_type"
            continue
        decisions = tuple(effective.capabilities[key] for key in capability_keys)
        if all(decision.state is CapabilityState.SUPPORTED for decision in decisions):
            supported.add(predicate)
            continue
        blocking = next(
            (
                decision
                for decision in decisions
                if decision.state is CapabilityState.UNSUPPORTED
            ),
            None,
        )
        if blocking is None:
            blocking = next(
                decision
                for decision in decisions
                if decision.state is CapabilityState.UNKNOWN
            )
        failures[predicate] = blocking.reason_id
    return CapabilityPredicateAdmission(
        supported=frozenset(supported),
        failure_reasons=MappingProxyType(failures),
        capability_revision=effective.revision,
    )
