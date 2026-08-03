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
    NormalizedResponseFormat,
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
