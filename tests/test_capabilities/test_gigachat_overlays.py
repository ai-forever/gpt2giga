"""Reviewed GigaChat capability overlay tests."""

from gpt2giga.capabilities import (
    CapabilityKey,
    CapabilitySource,
    CapabilityState,
    load_gigachat_capability_overlays,
    resolve_gigachat_model_layer,
)


def test_packaged_overlays_are_versioned_and_revision_stable() -> None:
    first = load_gigachat_capability_overlays()
    second = load_gigachat_capability_overlays()

    assert first.schema_version == "gpt2giga.gigachat-capability-overlays.v1"
    assert first.revision == second.revision
    assert all(
        overlay.selector.startswith("^") and overlay.selector.endswith("$")
        for overlay in first.overlays
        if overlay.selector_kind == "family"
    )


def test_exact_max_v2_overlay_adds_hosted_tools_over_family_baseline() -> None:
    layer = resolve_gigachat_model_layer("GigaChat-2-Max", "v2")

    assert layer.capabilities[CapabilityKey.TEXT_INPUT].state is (
        CapabilityState.SUPPORTED
    )
    assert layer.capabilities[CapabilityKey.TEXT_INPUT].source is (
        CapabilitySource.FAMILY_OVERLAY
    )
    assert layer.capabilities[CapabilityKey.HOSTED_WEB_SEARCH].state is (
        CapabilityState.SUPPORTED
    )
    assert layer.capabilities[CapabilityKey.HOSTED_WEB_SEARCH].source is (
        CapabilitySource.EXACT_MODEL_OVERLAY
    )
    assert layer.capabilities[CapabilityKey.IMAGE_INPUT].state is (
        CapabilityState.SUPPORTED
    )


def test_api_mode_constraint_does_not_expand_v1_hosted_tools() -> None:
    layer = resolve_gigachat_model_layer("GigaChat-2-Max", "v1")

    assert layer.capabilities[CapabilityKey.HOSTED_WEB_SEARCH].state is (
        CapabilityState.UNKNOWN
    )
    assert layer.capabilities[CapabilityKey.HOSTED_WEB_SEARCH].source is (
        CapabilitySource.UNRESOLVED
    )


def test_reviewed_reasoning_family_is_narrow_and_does_not_invent_summary() -> None:
    layer = resolve_gigachat_model_layer("GigaChat-2-Reasoning-preview", "v2")

    assert layer.capabilities[CapabilityKey.REASONING_CONTROLS].state is (
        CapabilityState.SUPPORTED
    )
    assert layer.capabilities[CapabilityKey.REASONING_SUMMARY].state is (
        CapabilityState.UNKNOWN
    )


def test_unknown_future_model_remains_visible_with_unknown_capabilities() -> None:
    layer = resolve_gigachat_model_layer("GigaChat-4-Future", "v2")

    assert {decision.state for decision in layer.capabilities.values()} == {
        CapabilityState.UNKNOWN
    }
    assert {decision.source for decision in layer.capabilities.values()} == {
        CapabilitySource.UNRESOLVED
    }
    assert layer.scope_id == "GigaChat-4-Future"
