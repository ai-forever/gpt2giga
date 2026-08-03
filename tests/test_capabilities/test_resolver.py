"""Effective capability intersection tests."""

from gpt2giga.capabilities import (
    CapabilityKey,
    CapabilityScope,
    CapabilitySource,
    CapabilityState,
    EffectiveCapabilityResolver,
    apply_provider_capability_metadata,
    build_capability_layer,
    resolve_gigachat_model_layer,
)


def _layers(
    *,
    protocol: CapabilityState = CapabilityState.SUPPORTED,
    adapter: CapabilityState = CapabilityState.SUPPORTED,
    model: CapabilityState = CapabilityState.SUPPORTED,
    api_mode: CapabilityState = CapabilityState.SUPPORTED,
    route: CapabilityState = CapabilityState.SUPPORTED,
):
    return {
        "public_protocol_layer": build_capability_layer(
            scope=CapabilityScope.PUBLIC_PROTOCOL,
            scope_id="openai_responses",
            source=CapabilitySource.PUBLIC_PROTOCOL,
            default_state=protocol,
        ),
        "provider_adapter_layer": build_capability_layer(
            scope=CapabilityScope.PROVIDER_ADAPTER,
            scope_id="gigachat",
            source=CapabilitySource.PROVIDER_ADAPTER,
            default_state=adapter,
        ),
        "model_layer": build_capability_layer(
            scope=CapabilityScope.MODEL,
            scope_id="GigaChat-2-Max",
            source=CapabilitySource.EXACT_MODEL_OVERLAY,
            default_state=model,
        ),
        "api_mode_layer": build_capability_layer(
            scope=CapabilityScope.API_MODE,
            scope_id="v2",
            source=CapabilitySource.API_MODE,
            default_state=api_mode,
        ),
        "route_policy_layer": build_capability_layer(
            scope=CapabilityScope.ROUTE_POLICY,
            scope_id="giga-main",
            source=CapabilitySource.ROUTE_POLICY,
            default_state=route,
        ),
    }


def _resolve(**layer_states):
    resolver = EffectiveCapabilityResolver()
    return resolver.resolve(
        model_id="GigaChat-2-Max",
        provider_kind="gigachat",
        public_protocol="openai_responses",
        api_mode="v2",
        **_layers(**layer_states),
    )


def test_any_unsupported_layer_makes_effective_capability_unsupported() -> None:
    result = _resolve(
        protocol=CapabilityState.UNKNOWN,
        model=CapabilityState.UNSUPPORTED,
    )

    decision = result.capabilities[CapabilityKey.HOSTED_WEB_SEARCH]
    assert decision.state is CapabilityState.UNSUPPORTED
    assert decision.reason_id == "model_blocks_capability"
    assert decision.source is CapabilitySource.EXACT_MODEL_OVERLAY


def test_unknown_survives_when_no_layer_is_unsupported() -> None:
    result = _resolve(adapter=CapabilityState.UNKNOWN)

    decision = result.capabilities[CapabilityKey.JSON_SCHEMA_OUTPUT]
    assert decision.state is CapabilityState.UNKNOWN
    assert decision.reason_id == "provider_adapter_capability_unknown"


def test_all_supported_layers_produce_supported_with_stable_revision() -> None:
    first = _resolve()
    second = _resolve()

    assert {decision.state for decision in first.capabilities.values()} == {
        CapabilityState.SUPPORTED
    }
    assert first.revision == second.revision
    assert first.capabilities[CapabilityKey.TEXT_INPUT].reason_id == (
        "all_layers_supported"
    )


def test_route_policy_can_narrow_but_cannot_expand_model_support() -> None:
    model_blocked = _resolve(model=CapabilityState.UNSUPPORTED)
    route_blocked = _resolve(route=CapabilityState.UNSUPPORTED)

    assert model_blocked.capabilities[CapabilityKey.FILE_INPUT].state is (
        CapabilityState.UNSUPPORTED
    )
    assert route_blocked.capabilities[CapabilityKey.FILE_INPUT].reason_id == (
        "route_policy_blocks_capability"
    )


def test_explicit_provider_metadata_outranks_overlay_without_name_inference() -> None:
    unknown = resolve_gigachat_model_layer("GigaChat-4-Future", "v2")
    refined = apply_provider_capability_metadata(
        unknown,
        {
            CapabilityKey.TEXT_INPUT: True,
            CapabilityKey.HOSTED_WEB_SEARCH: "unsupported",
        },
        evidence_id="PROVIDER-MODEL-METADATA-REV-7",
    )

    assert refined.capabilities[CapabilityKey.TEXT_INPUT].state is (
        CapabilityState.SUPPORTED
    )
    assert refined.capabilities[CapabilityKey.TEXT_INPUT].source is (
        CapabilitySource.PROVIDER_METADATA
    )
    assert refined.capabilities[CapabilityKey.HOSTED_WEB_SEARCH].state is (
        CapabilityState.UNSUPPORTED
    )
    assert refined.capabilities[CapabilityKey.REASONING_CONTROLS].state is (
        CapabilityState.UNKNOWN
    )
