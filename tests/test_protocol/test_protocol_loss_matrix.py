import json

import pytest

from gpt2giga.protocols.normalized import (
    PROTOCOL_LOSS_MATRIX_SCHEMA_VERSION,
    PROTOCOL_LOSS_MATRIX_V1,
    BridgeFeature,
    DownstreamProtocol,
    LossDisposition,
    NormalizedCancellation,
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedImageReference,
    NormalizedMessage,
    NormalizedProtocolCapabilities,
    NormalizedResponseFormat,
    NormalizedTokenCountRequest,
    NormalizedTokenLimits,
    NormalizedTool,
    UnsupportedSemanticLossError,
    admit_protocol_bridge_request,
    protocol_loss_matrix_json,
)


def _capabilities(*, features=frozenset(BridgeFeature)):
    return NormalizedProtocolCapabilities(
        profile="hermetic-openai-compatible",
        features=features,
        limits=NormalizedTokenLimits(
            context_window=8192,
            max_input_tokens=6144,
            max_output_tokens=2048,
        ),
    )


def _complex_request(*, parallel_tool_calls=False):
    return NormalizedChatRequest(
        model="local-model",
        stream=True,
        messages=[
            NormalizedMessage(role="system", content="Be concise."),
            NormalizedMessage(
                role="user",
                content=[
                    NormalizedContentPart(type="text", text="Inspect this."),
                    NormalizedContentPart(
                        type="image_reference",
                        image_reference=NormalizedImageReference(
                            source="url",
                            uri="https://example.invalid/image.png",
                            mime_type="image/png",
                        ),
                    ),
                ],
            ),
            NormalizedMessage(
                role="tool",
                tool_call_id="call-1",
                content='{"status":"ok"}',
            ),
        ],
        tools=[
            NormalizedTool(
                name="lookup",
                parameters={"type": "object", "properties": {}},
            )
        ],
        tool_choice={"type": "function", "function": {"name": "lookup"}},
        parallel_tool_calls=parallel_tool_calls,
        response_format=NormalizedResponseFormat(
            type="json_schema",
            json_schema={"name": "answer", "schema": {"type": "object"}},
        ),
        generation_config=NormalizedGenerationConfig(max_tokens=128),
        cancellation=NormalizedCancellation(mode="client_disconnect"),
    )


def test_protocol_loss_matrix_is_complete_versioned_and_json_serializable():
    expected = set(BridgeFeature)

    assert set(PROTOCOL_LOSS_MATRIX_V1) == set(DownstreamProtocol)
    assert all(set(rules) == expected for rules in PROTOCOL_LOSS_MATRIX_V1.values())
    assert (
        PROTOCOL_LOSS_MATRIX_V1[DownstreamProtocol.GEMINI][
            BridgeFeature.PARALLEL_TOOL_CALLS
        ].disposition
        is LossDisposition.UNSUPPORTED
    )

    payload = protocol_loss_matrix_json()
    assert payload["schema_version"] == PROTOCOL_LOSS_MATRIX_SCHEMA_VERSION
    assert payload["implementation_status"] == "openai_compatible_upstream_adapter"
    json.dumps(payload)


def test_bridge_admission_accepts_exact_and_reviewed_conditional_semantics():
    request = _complex_request()
    conditional = {
        feature
        for feature, rule in PROTOCOL_LOSS_MATRIX_V1[
            DownstreamProtocol.ANTHROPIC
        ].items()
        if rule.disposition is LossDisposition.CONDITIONAL
    }

    admission = admit_protocol_bridge_request(
        request,
        downstream=DownstreamProtocol.ANTHROPIC,
        upstream=_capabilities(),
        downstream_capabilities=conditional,
        input_token_count=256,
    )

    assert admission.schema_version == "gigaloom.protocol-bridge-admission.v1"
    assert BridgeFeature.IMAGE_REFERENCES in admission.required_features
    assert BridgeFeature.JSON_SCHEMA_OUTPUT in admission.required_features
    assert BridgeFeature.STREAM_TERMINAL_EVENTS in admission.required_features


def test_bridge_admission_rejects_conditional_semantics_without_reviewed_capability():
    with pytest.raises(UnsupportedSemanticLossError, match="image_references"):
        admit_protocol_bridge_request(
            _complex_request(),
            downstream=DownstreamProtocol.ANTHROPIC,
            upstream=_capabilities(),
        )


def test_bridge_admission_rejects_unsupported_semantics_before_transport():
    transport_called = False

    def execute_after_admission():
        nonlocal transport_called
        admit_protocol_bridge_request(
            _complex_request(parallel_tool_calls=True),
            downstream=DownstreamProtocol.GEMINI,
            upstream=_capabilities(),
            downstream_capabilities=frozenset(BridgeFeature),
        )
        transport_called = True

    with pytest.raises(UnsupportedSemanticLossError, match="parallel_tool_calls"):
        execute_after_admission()

    assert transport_called is False


@pytest.mark.parametrize(
    "normalized_case",
    [
        NormalizedChatRequest(
            messages=[NormalizedMessage(role="developer", content="hidden")]
        ),
        NormalizedChatRequest(
            messages=[
                NormalizedMessage(
                    role="user",
                    content=[
                        NormalizedContentPart(type="file", data={"file_id": "file-1"})
                    ],
                )
            ]
        ),
        NormalizedChatRequest(raw_extensions={"unmodeled": True}),
    ],
)
def test_bridge_admission_rejects_meaning_outside_normalized_v1(normalized_case):
    with pytest.raises(UnsupportedSemanticLossError, match="normalized v1|unmodeled"):
        admit_protocol_bridge_request(
            normalized_case,
            downstream=DownstreamProtocol.OPENAI,
            upstream=_capabilities(),
            downstream_capabilities=frozenset(BridgeFeature),
        )


def test_bridge_admission_enforces_declared_token_limits():
    request = NormalizedChatRequest(
        messages=[NormalizedMessage(role="user", content="hello")],
        generation_config=NormalizedGenerationConfig(max_tokens=512),
    )

    with pytest.raises(UnsupportedSemanticLossError, match="context window"):
        admit_protocol_bridge_request(
            request,
            downstream=DownstreamProtocol.OPENAI,
            upstream=_capabilities(),
            downstream_capabilities=frozenset(BridgeFeature),
            input_token_count=8000,
        )


def test_count_tokens_is_explicitly_admitted_or_rejected_by_downstream():
    request = NormalizedTokenCountRequest(
        input=NormalizedChatRequest(
            messages=[NormalizedMessage(role="user", content="hello")]
        )
    )
    anthropic = admit_protocol_bridge_request(
        request,
        downstream=DownstreamProtocol.ANTHROPIC,
        upstream=_capabilities(),
        downstream_capabilities=frozenset(BridgeFeature),
    )

    assert BridgeFeature.COUNT_TOKENS in anthropic.required_features
    with pytest.raises(UnsupportedSemanticLossError, match="count_tokens"):
        admit_protocol_bridge_request(
            request,
            downstream=DownstreamProtocol.OPENAI,
            upstream=_capabilities(),
            downstream_capabilities=frozenset(BridgeFeature),
        )
