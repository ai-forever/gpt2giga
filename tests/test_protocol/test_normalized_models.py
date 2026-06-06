import json

import pytest
from pydantic import ValidationError

from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedEmbeddingRequest,
    NormalizedError,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedResponseFormat,
    NormalizedStreamEvent,
    NormalizedTool,
    NormalizedToolCall,
    NormalizedUsage,
)


def test_normalized_chat_request_preserves_extensions_and_serializes_to_json():
    request = NormalizedChatRequest(
        model="GigaChat-2-Max",
        stream=False,
        messages=[
            NormalizedMessage(role="system", content="Be concise."),
            NormalizedMessage(
                role="user",
                content=[
                    NormalizedContentPart(type="text", text="ping"),
                    NormalizedContentPart(
                        type="image",
                        data={"file_id": "file-1"},
                        mime_type="image/png",
                    ),
                ],
            ),
        ],
        tools=[
            NormalizedTool(
                name="lookup",
                description="Lookup data.",
                parameters={"type": "object", "properties": {"q": {"type": "string"}}},
            )
        ],
        tool_choice={"type": "function", "function": {"name": "lookup"}},
        response_format=NormalizedResponseFormat(
            type="json_schema",
            json_schema={"name": "answer", "schema": {"type": "object"}},
        ),
        generation_config=NormalizedGenerationConfig(
            temperature=0.2,
            max_tokens=128,
            stop=["</done>"],
        ),
        metadata={"client": "test"},
        raw_extensions={"parallel_tool_calls": False},
        provider_metadata={"gigachat": {"profanity_check": False}},
    )

    payload = request.to_json_dict()

    assert payload["operation"] == "chat"
    assert payload["messages"][1]["content"][1]["mime_type"] == "image/png"
    assert payload["raw_extensions"] == {"parallel_tool_calls": False}
    assert payload["provider_metadata"] == {"gigachat": {"profanity_check": False}}
    json.dumps(payload)


def test_normalized_response_and_stream_event_are_json_serializable():
    message = NormalizedMessage(
        role="assistant",
        content="Done.",
        tool_calls=[
            NormalizedToolCall(id="call-1", name="lookup", arguments={"q": "ping"})
        ],
    )
    response = NormalizedResponse(
        id="resp-1",
        model="GigaChat-2-Max",
        provider="gigachat",
        choices=[NormalizedChoice(index=0, message=message, finish_reason="stop")],
        usage=NormalizedUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        metadata={"upstream_request_id": "upstream-1"},
    )
    event = NormalizedStreamEvent(
        type="content_delta",
        sequence=1,
        delta=NormalizedMessage(role="assistant", content="Do"),
        provider_metadata={"gigachat": {"chunk": 1}},
    )

    response_payload = response.to_json_dict()
    event_payload = event.to_json_dict()

    assert response_payload["created_at"]
    assert response_payload["choices"][0]["message"]["tool_calls"][0]["arguments"] == {
        "q": "ping"
    }
    assert event_payload["type"] == "content_delta"
    assert event_payload["provider_metadata"] == {"gigachat": {"chunk": 1}}
    json.dumps(response_payload)
    json.dumps(event_payload)


def test_normalized_embedding_request_supports_provider_metadata():
    request = NormalizedEmbeddingRequest(
        model="EmbeddingsGigaR",
        input=["one", "two"],
        dimensions=512,
        encoding_format="float",
        user="user-1",
        raw_extensions={"encoding_source": "openai"},
        provider_metadata={"gigachat": {"scope": "test"}},
    )

    payload = request.to_json_dict()

    assert payload["operation"] == "embeddings"
    assert payload["input"] == ["one", "two"]
    assert payload["dimensions"] == 512
    assert payload["provider_metadata"]["gigachat"]["scope"] == "test"


def test_normalized_models_reject_implicit_extra_fields():
    with pytest.raises(ValidationError):
        NormalizedMessage(role="user", content="hello", unexpected=True)


def test_normalized_error_can_be_embedded_in_response():
    response = NormalizedResponse(
        error=NormalizedError(type="upstream_error", message="bad upstream", code=500)
    )

    payload = response.to_json_dict()

    assert payload["error"] == {
        "type": "upstream_error",
        "message": "bad upstream",
        "code": 500,
        "raw_extensions": {},
        "provider_metadata": {},
    }
