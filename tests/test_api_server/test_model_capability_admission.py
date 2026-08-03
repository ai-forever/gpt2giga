"""Application binding for selected-model capability admission."""

import pytest
from fastapi.testclient import TestClient

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocols.normalized import (
    BridgeMatrixAdmissionError,
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedImageReference,
    NormalizedMessage,
    NormalizedReasoningIntent,
    NormalizedResponseFormat,
    NormalizedStateIntent,
    NormalizedTool,
    NormalizedToolKind,
)


def _app():
    return create_app(
        ProxyConfig(
            gigachat={"model": "GigaChat-2-Max"},
            proxy={"gigachat_api_mode": "v2"},
        )
    )


def test_runtime_admits_selected_model_image_predicates() -> None:
    app = _app()
    request = NormalizedChatRequest(
        model="GigaChat-2-Max",
        messages=[
            NormalizedMessage(
                role="user",
                content=[
                    NormalizedContentPart(
                        type="image_reference",
                        image_reference=NormalizedImageReference(
                            source="data_url",
                            uri="data:image/png;base64,AA==",
                        ),
                    )
                ],
            )
        ],
    )

    with TestClient(app):
        adapter = app.state.bridge_provider_runtime.adapter_for(
            request,
            api_mode="v2",
        )

    assert adapter.forced_model == "GigaChat-2-Max"


def test_runtime_rejects_unproven_selected_model_semantic_with_exact_reason() -> None:
    app = _app()
    request = NormalizedChatRequest(
        model="GigaChat-2-Max",
        response_format=NormalizedResponseFormat(
            type="json_schema",
            json_schema={"type": "object"},
        ),
    )

    with TestClient(app), pytest.raises(BridgeMatrixAdmissionError) as captured:
        app.state.bridge_provider_runtime.adapter_for(request, api_mode="v2")

    assert captured.value.public_field_path == "text.format"
    assert captured.value.reason_id == "unreviewed_model_capability"


def test_runtime_admits_reviewed_hosted_web_tool_for_selected_v2_model() -> None:
    app = _app()
    request = NormalizedChatRequest(
        model="GigaChat-2-Max",
        tools=[
            NormalizedTool(
                kind=NormalizedToolKind.HOSTED,
                type="web_search_preview",
                configuration={"search_context_size": "medium"},
            )
        ],
    )

    with TestClient(app):
        adapter = app.state.bridge_provider_runtime.adapter_for(
            request,
            api_mode="v2",
        )

    assert adapter.forced_model == "GigaChat-2-Max"


def test_runtime_rejects_hosted_web_tool_for_v1_before_dispatch() -> None:
    app = _app()
    request = NormalizedChatRequest(
        model="GigaChat-2-Max",
        tools=[
            NormalizedTool(
                kind=NormalizedToolKind.HOSTED,
                type="web_search_preview",
            )
        ],
    )

    with TestClient(app), pytest.raises(BridgeMatrixAdmissionError) as captured:
        app.state.bridge_provider_runtime.adapter_for(request, api_mode="v1")

    assert captured.value.public_field_path == "tools[0].type"
    assert captured.value.reason_id == "api_mode_blocks_capability"


@pytest.mark.parametrize(
    ("request_kwargs", "field"),
    [
        ({"reasoning": NormalizedReasoningIntent(effort="high")}, "reasoning"),
        (
            {
                "response_state": NormalizedStateIntent(
                    previous_response_id="resp_previous"
                )
            },
            "previous_response_id",
        ),
        (
            {"response_state": NormalizedStateIntent(conversation_id="conv_previous")},
            "conversation",
        ),
    ],
)
def test_runtime_rejects_preserved_unproven_intent_after_route_resolution(
    request_kwargs: dict,
    field: str,
) -> None:
    app = _app()
    request = NormalizedChatRequest(
        model="GigaChat-2-Max",
        **request_kwargs,
    )

    with TestClient(app), pytest.raises(BridgeMatrixAdmissionError) as captured:
        app.state.bridge_provider_runtime.adapter_for(request, api_mode="v2")

    assert captured.value.public_field_path == field
    assert captured.value.reason_id == "semantic_not_proven"
