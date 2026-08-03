"""Effective protocol/provider/model/API-mode/route capability resolution."""

from __future__ import annotations

from collections.abc import Mapping

from gpt2giga.capabilities.models import (
    CAPABILITY_KEYS_V1,
    CapabilityDecision,
    CapabilityEvidence,
    CapabilityKey,
    CapabilityLayer,
    CapabilityScope,
    CapabilitySource,
    CapabilityState,
    EffectiveModelCapabilities,
    capability_revision,
)


class EffectiveCapabilityResolver:
    """Intersect complete capability layers without collapsing unknown facts."""

    def resolve(
        self,
        *,
        model_id: str,
        provider_kind: str,
        public_protocol: str,
        api_mode: str | None,
        public_protocol_layer: CapabilityLayer,
        provider_adapter_layer: CapabilityLayer,
        model_layer: CapabilityLayer,
        api_mode_layer: CapabilityLayer,
        route_policy_layer: CapabilityLayer,
    ) -> EffectiveModelCapabilities:
        """Return one deterministic effective result for an exact route."""
        layers = (
            public_protocol_layer,
            provider_adapter_layer,
            model_layer,
            api_mode_layer,
            route_policy_layer,
        )
        expected_scopes = (
            CapabilityScope.PUBLIC_PROTOCOL,
            CapabilityScope.PROVIDER_ADAPTER,
            CapabilityScope.MODEL,
            CapabilityScope.API_MODE,
            CapabilityScope.ROUTE_POLICY,
        )
        actual_scopes = tuple(layer.scope for layer in layers)
        if actual_scopes != expected_scopes:
            raise ValueError(
                "capability layers must be supplied in protocol, adapter, model, "
                "API-mode, and route-policy order"
            )
        if model_layer.scope_id != model_id:
            raise ValueError("model capability layer does not match selected model")

        effective = {
            key: _intersect_decisions(key, layers) for key in CAPABILITY_KEYS_V1
        }
        evidence_by_id = {
            item.evidence_id: item for layer in layers for item in layer.evidence
        }
        result_payload = {
            "schema_version": "gpt2giga.model-capabilities.v1",
            "model_id": model_id,
            "provider_kind": provider_kind,
            "public_protocol": public_protocol,
            "api_mode": api_mode,
            "capabilities": {
                key.value: decision.model_dump(mode="json")
                for key, decision in effective.items()
            },
            "layer_revisions": [layer.revision for layer in layers],
        }
        return EffectiveModelCapabilities(
            model_id=model_id,
            provider_kind=provider_kind,
            public_protocol=public_protocol,
            api_mode=api_mode,
            capabilities=effective,
            revision=capability_revision(result_payload),
            evidence=tuple(evidence_by_id.values()),
            layer_revisions=tuple(layer.revision for layer in layers),
        )


def build_capability_layer(
    *,
    scope: CapabilityScope,
    scope_id: str,
    source: CapabilitySource,
    states: Mapping[CapabilityKey, CapabilityState] | None = None,
    default_state: CapabilityState = CapabilityState.UNKNOWN,
    evidence_ids: tuple[str, ...] = (),
) -> CapabilityLayer:
    """Build a complete reviewed input layer from sparse explicit states."""
    explicit = states or {}
    revision = capability_revision(
        {
            "scope": scope.value,
            "scope_id": scope_id,
            "source": source.value,
            "default_state": default_state.value,
            "states": {
                key.value: state.value
                for key, state in sorted(
                    explicit.items(), key=lambda item: item[0].value
                )
            },
            "evidence_ids": sorted(set(evidence_ids)),
        }
    )
    decisions = {
        key: CapabilityDecision(
            state=explicit.get(key, default_state),
            reason_id=_layer_reason_id(scope, explicit.get(key, default_state)),
            source=source,
            evidence_ids=evidence_ids,
            revision=capability_revision(
                {
                    "layer_revision": revision,
                    "capability": key.value,
                    "state": explicit.get(key, default_state).value,
                }
            ),
        )
        for key in CAPABILITY_KEYS_V1
    }
    evidence = tuple(
        CapabilityEvidence(
            evidence_id=evidence_id,
            source=source,
            revision=revision,
        )
        for evidence_id in evidence_ids
    )
    return CapabilityLayer(
        scope=scope,
        scope_id=scope_id,
        capabilities=decisions,
        revision=revision,
        evidence=evidence,
    )


def apply_provider_capability_metadata(
    model_layer: CapabilityLayer,
    provider_capabilities: Mapping[CapabilityKey | str, CapabilityState | str | bool],
    *,
    evidence_id: str,
) -> CapabilityLayer:
    """Apply only explicit provider metadata above reviewed overlay decisions."""
    if model_layer.scope is not CapabilityScope.MODEL:
        raise ValueError("provider model metadata can only refine a model layer")
    normalized = {
        CapabilityKey(key): _provider_state(value)
        for key, value in provider_capabilities.items()
    }
    metadata_revision = capability_revision(
        {
            "base_revision": model_layer.revision,
            "provider_capabilities": {
                key.value: state.value
                for key, state in sorted(
                    normalized.items(), key=lambda item: item[0].value
                )
            },
            "evidence_id": evidence_id,
        }
    )
    decisions = dict(model_layer.capabilities)
    for key, state in normalized.items():
        decisions[key] = CapabilityDecision(
            state=state,
            reason_id=f"provider_metadata_{state.value}",
            source=CapabilitySource.PROVIDER_METADATA,
            evidence_ids=(evidence_id,),
            revision=capability_revision(
                {
                    "metadata_revision": metadata_revision,
                    "capability": key.value,
                    "state": state.value,
                }
            ),
        )
    metadata_evidence = CapabilityEvidence(
        evidence_id=evidence_id,
        source=CapabilitySource.PROVIDER_METADATA,
        revision=metadata_revision,
    )
    return CapabilityLayer(
        scope=model_layer.scope,
        scope_id=model_layer.scope_id,
        capabilities=decisions,
        revision=metadata_revision,
        evidence=(*model_layer.evidence, metadata_evidence),
    )


def _intersect_decisions(
    key: CapabilityKey,
    layers: tuple[CapabilityLayer, ...],
) -> CapabilityDecision:
    inputs = tuple(layer.capabilities[key] for layer in layers)
    unsupported = tuple(
        decision
        for decision in reversed(inputs)
        if decision.state is CapabilityState.UNSUPPORTED
    )
    unknown = tuple(
        decision
        for decision in reversed(inputs)
        if decision.state is CapabilityState.UNKNOWN
    )
    if unsupported:
        selected = unsupported[0]
        state = CapabilityState.UNSUPPORTED
        reason_id = selected.reason_id
        source = selected.source
    elif unknown:
        selected = unknown[0]
        state = CapabilityState.UNKNOWN
        reason_id = selected.reason_id
        source = selected.source
    else:
        state = CapabilityState.SUPPORTED
        reason_id = "all_layers_supported"
        source = CapabilitySource.EFFECTIVE_INTERSECTION
    evidence_ids = tuple(
        sorted(
            {
                evidence_id
                for decision in inputs
                for evidence_id in decision.evidence_ids
            }
        )
    )
    revision = capability_revision(
        {
            "capability": key.value,
            "state": state.value,
            "reason_id": reason_id,
            "source": source.value,
            "input_revisions": [decision.revision for decision in inputs],
            "evidence_ids": evidence_ids,
        }
    )
    return CapabilityDecision(
        state=state,
        reason_id=reason_id,
        source=source,
        evidence_ids=evidence_ids,
        revision=revision,
    )


def _layer_reason_id(
    scope: CapabilityScope,
    state: CapabilityState,
) -> str:
    suffix = {
        CapabilityState.SUPPORTED: "supports_capability",
        CapabilityState.UNSUPPORTED: "blocks_capability",
        CapabilityState.UNKNOWN: "capability_unknown",
    }[state]
    return f"{scope.value}_{suffix}"


def _provider_state(value: CapabilityState | str | bool) -> CapabilityState:
    if isinstance(value, bool):
        return CapabilityState.SUPPORTED if value else CapabilityState.UNSUPPORTED
    return CapabilityState(value)
