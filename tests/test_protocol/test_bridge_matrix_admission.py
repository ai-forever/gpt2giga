import json

import pytest
from pydantic import ValidationError

from gpt2giga.protocols.normalized.loss_matrix import (
    BRIDGE_LOSS_MATRIX_V1,
    BridgeAdmissionDecision,
    BridgeLossMatrix,
    BridgeMatrixAdmissionError,
    BridgeSemantic,
    BridgeSupportStatus,
    PublicProtocol,
    UpstreamProvider,
    admit_bridge_route,
    admit_then_dispatch_bridge_route,
)


def _route_kwargs(**overrides):
    values = {
        "public_protocol": PublicProtocol.OPENAI_CHAT_COMPLETIONS,
        "public_alias": "giga/max",
        "upstream_provider": UpstreamProvider.GIGACHAT,
        "profile_id": "giga-main",
        "config_revision": "sha256:config",
        "capability_profile_revision": "giga-max-v1",
        "requested_semantics": {BridgeSemantic.ROLES: "messages"},
    }
    values.update(overrides)
    return values


def test_exact_semantics_produce_content_free_revision_bound_decision() -> None:
    decision = admit_bridge_route(**_route_kwargs())

    assert decision.schema_version == "gpt2giga.bridge-admission.v1"
    assert decision.support_status is BridgeSupportStatus.STABLE
    assert decision.loss_matrix_revision == BRIDGE_LOSS_MATRIX_V1.revision
    assert decision.public_alias == "giga/max"
    assert decision.requested_semantics[0].public_field_path == "messages"
    serialized = json.dumps(decision.model_dump(mode="json")).lower()
    assert "prompt" not in serialized
    assert "credential" not in serialized
    assert "api_key" not in serialized


def test_custom_matrix_keeps_its_own_revision_and_admission_rules() -> None:
    custom = BridgeLossMatrix.model_validate(BRIDGE_LOSS_MATRIX_V1.canonical_payload())

    decision = admit_bridge_route(**_route_kwargs(), matrix=custom)

    assert decision.loss_matrix_revision == custom.revision


async def test_blocked_route_rejects_before_provider_dispatch() -> None:
    dispatch_calls: list[BridgeAdmissionDecision] = []

    async def dispatch(decision: BridgeAdmissionDecision) -> str:
        dispatch_calls.append(decision)
        return "dispatched"

    with pytest.raises(BridgeMatrixAdmissionError) as captured:
        await admit_then_dispatch_bridge_route(
            dispatch=dispatch,
            **_route_kwargs(upstream_provider=UpstreamProvider.OPENAI_COMPATIBLE),
        )

    assert captured.value.as_public_error() == {
        "code": "unsupported_semantic",
        "message": "The selected bridge route cannot preserve this semantic.",
        "param": "model",
        "type": "invalid_request_error",
    }
    assert captured.value.reason_id == "route_not_integrated"
    assert dispatch_calls == []


async def test_unsupported_semantic_rejects_before_provider_dispatch() -> None:
    dispatch_calls = 0

    async def dispatch(_decision: BridgeAdmissionDecision) -> str:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return "dispatched"

    with pytest.raises(BridgeMatrixAdmissionError) as captured:
        await admit_then_dispatch_bridge_route(
            dispatch=dispatch,
            **_route_kwargs(
                requested_semantics={
                    BridgeSemantic.REASONING_CONTROLS_AND_SUMMARIES: "reasoning"
                }
            ),
        )

    assert captured.value.public_field_path == "reasoning"
    assert captured.value.reason_id == "semantic_not_proven"
    assert dispatch_calls == 0


def test_conditional_semantic_requires_the_exact_capability_predicate() -> None:
    kwargs = _route_kwargs(
        requested_semantics={BridgeSemantic.MULTIMODAL_INPUTS: "messages[0].content"}
    )
    with pytest.raises(BridgeMatrixAdmissionError) as captured:
        admit_bridge_route(
            **kwargs,
            capability_predicates={"capability.multimodal"},
        )

    assert captured.value.reason_id == "requires_reviewed_capability"
    decision = admit_bridge_route(
        **kwargs,
        capability_predicates={"capability.multimodal_inputs"},
    )
    assert decision.satisfied_capability_predicates == ("capability.multimodal_inputs",)


async def test_dispatch_receives_exact_admission_once() -> None:
    decisions: list[BridgeAdmissionDecision] = []

    async def dispatch(decision: BridgeAdmissionDecision) -> str:
        decisions.append(decision)
        return "provider-result"

    result = await admit_then_dispatch_bridge_route(
        dispatch=dispatch,
        **_route_kwargs(),
    )

    assert result == "provider-result"
    assert len(decisions) == 1
    assert decisions[0].upstream_provider is UpstreamProvider.GIGACHAT
    assert decisions[0].profile_id == "giga-main"


async def test_invalid_route_identity_rejects_before_provider_dispatch() -> None:
    dispatch_calls = 0

    async def dispatch(_decision: BridgeAdmissionDecision) -> str:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return "dispatched"

    with pytest.raises(ValidationError):
        await admit_then_dispatch_bridge_route(
            dispatch=dispatch,
            **_route_kwargs(public_alias="request supplied secret?"),
        )

    assert dispatch_calls == 0
