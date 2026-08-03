"""Selected-model capability admission tests."""

import pytest

from gpt2giga.capabilities import (
    CapabilityKey,
    CapabilityState,
    capability_predicates_for_semantics,
    resolve_gigachat_route_capabilities,
)
from gpt2giga.protocols.normalized.loss_matrix import (
    BridgeMatrixAdmissionError,
    BridgeSemantic,
    PublicProtocol,
    UpstreamProvider,
    admit_bridge_route,
)


def _effective(model_id: str = "GigaChat-2-Max"):
    return resolve_gigachat_route_capabilities(
        model_id=model_id,
        public_protocol="openai_responses",
        api_mode="v2",
        route_id="giga-main",
    )


def _route_kwargs():
    return {
        "public_protocol": PublicProtocol.OPENAI_RESPONSES,
        "public_alias": "giga/max",
        "upstream_provider": UpstreamProvider.GIGACHAT,
        "profile_id": "giga-main",
        "config_revision": "sha256:config",
        "capability_profile_revision": "giga-max-v1",
    }


def test_supported_model_and_v2_produce_hosted_tool_capability() -> None:
    effective = _effective()

    assert effective.capabilities[CapabilityKey.HOSTED_WEB_SEARCH].state is (
        CapabilityState.SUPPORTED
    )
    assert effective.capabilities[CapabilityKey.HOSTED_CODE_INTERPRETER].state is (
        CapabilityState.SUPPORTED
    )


def test_route_configuration_can_narrow_hosted_tool_support() -> None:
    effective = resolve_gigachat_route_capabilities(
        model_id="GigaChat-2-Max",
        public_protocol="openai_responses",
        api_mode="v2",
        route_id="giga-main",
        builtin_tools_enabled=False,
    )

    decision = effective.capabilities[CapabilityKey.HOSTED_WEB_SEARCH]
    assert decision.state is CapabilityState.UNSUPPORTED
    assert decision.reason_id == "provider_adapter_blocks_capability"


def test_selected_model_image_evidence_satisfies_exact_matrix_predicates() -> None:
    semantics = {
        BridgeSemantic.MULTIMODAL_INPUTS: "input",
        BridgeSemantic.FILES_AND_IMAGES: "input",
    }
    predicates = capability_predicates_for_semantics(_effective(), semantics)

    decision = admit_bridge_route(
        **_route_kwargs(),
        requested_semantics=semantics,
        capability_predicates=predicates.supported,
        capability_predicate_reasons=predicates.failure_reasons,
    )

    assert decision.satisfied_capability_predicates == (
        "capability.files_and_images",
        "capability.multimodal_inputs",
    )


@pytest.mark.parametrize(
    ("semantic", "expected_reason"),
    [
        (
            BridgeSemantic.STRUCTURED_OUTPUT_JSON_SCHEMA,
            "unreviewed_model_capability",
        ),
        (
            BridgeSemantic.PARALLEL_TOOL_CALLS,
            "provider_adapter_blocks_capability",
        ),
    ],
)
def test_unsatisfied_predicate_names_exact_model_or_adapter_reason(
    semantic: BridgeSemantic,
    expected_reason: str,
) -> None:
    semantics = {semantic: "request.field"}
    predicates = capability_predicates_for_semantics(_effective(), semantics)

    with pytest.raises(BridgeMatrixAdmissionError) as captured:
        admit_bridge_route(
            **_route_kwargs(),
            requested_semantics=semantics,
            capability_predicates=predicates.supported,
            capability_predicate_reasons=predicates.failure_reasons,
        )

    assert captured.value.public_field_path == "request.field"
    assert captured.value.reason_id == expected_reason


def test_unknown_future_model_is_not_silently_admitted() -> None:
    semantics = {BridgeSemantic.MULTIMODAL_INPUTS: "input[0].content"}
    predicates = capability_predicates_for_semantics(
        _effective("GigaChat-4-Future"),
        semantics,
    )

    with pytest.raises(BridgeMatrixAdmissionError) as captured:
        admit_bridge_route(
            **_route_kwargs(),
            requested_semantics=semantics,
            capability_predicates=predicates.supported,
            capability_predicate_reasons=predicates.failure_reasons,
        )

    assert captured.value.reason_id == "unreviewed_model_capability"
