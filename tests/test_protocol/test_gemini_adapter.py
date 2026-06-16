import json
from datetime import datetime, timezone

from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.gemini import GeminiProtocolAdapter
from gpt2giga.protocols.gemini.response_adapter import (
    normalized_chat_response_to_gemini,
)
from gpt2giga.protocols.gemini.streaming import (
    normalized_stream_event_to_gemini_chunk,
)
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)


def test_gemini_adapter_maps_generate_content_to_normalized_request():
    adapter = GeminiProtocolAdapter()
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id=None,
        protocol="gemini",
        route="/v1beta/models/gemini-pro:generateContent",
        method="POST",
        started_at=datetime.now(timezone.utc),
        model_requested="gemini-pro",
    )

    normalized = adapter.generate_content_to_normalized(
        {
            "systemInstruction": {"parts": [{"text": "Be concise."}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "Describe this image"},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": "AA==",
                            }
                        },
                    ],
                }
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup",
                            "description": "Lookup data.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "q": {"type": "STRING"},
                                    "answers": {"type": "OBJECT"},
                                    "limit": {"type": ["INTEGER", "NULL"]},
                                },
                            },
                        }
                    ]
                }
            ],
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": ["lookup"],
                }
            },
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8,
                "maxOutputTokens": 64,
                "stopSequences": ["</done>"],
                "responseMimeType": "application/json",
                "responseSchema": {"type": "object"},
                "topK": 20,
            },
            "safetySettings": [{"category": "HARM_CATEGORY_HARASSMENT"}],
        },
        model="gemini-pro",
        context=context,
    )

    payload = normalized.to_json_dict()

    assert payload["id"] == "req-1"
    assert payload["protocol"] == "gemini"
    assert payload["model"] == "gemini-pro"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"][0]["text"] == "Describe this image"
    assert payload["messages"][1]["content"][1]["type"] == "image_url"
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["tools"][0]["parameters"]["type"] == "object"
    assert payload["tools"][0]["parameters"]["properties"]["q"]["type"] == "string"
    assert payload["tools"][0]["parameters"]["properties"]["answers"] == {
        "type": "object",
        "properties": {},
    }
    assert payload["tools"][0]["parameters"]["properties"]["limit"]["type"] == (
        "integer"
    )
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "lookup"},
    }
    assert payload["generation_config"]["temperature"] == 0.2
    assert payload["generation_config"]["max_tokens"] == 64
    assert payload["generation_config"]["raw_extensions"]["topK"] == 20
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["raw_extensions"]["safetySettings"][0]["category"] == (
        "HARM_CATEGORY_HARASSMENT"
    )
    json.dumps(payload)


def test_gemini_response_adapter_maps_normalized_response():
    response = NormalizedResponse(
        id="req-1",
        model="gemini-pro",
        provider="gigachat",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(
                    role="assistant",
                    content="ok",
                    tool_calls=[
                        NormalizedToolCall(name="lookup", arguments='{"q":"ping"}')
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=NormalizedUsage(input_tokens=2, output_tokens=3, total_tokens=5),
    )

    payload = normalized_chat_response_to_gemini(
        response,
        requested_model="gemini-pro",
    )

    assert payload["responseId"] == "req-1"
    assert payload["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 3,
        "totalTokenCount": 5,
    }
    candidate = payload["candidates"][0]
    assert candidate["content"]["role"] == "model"
    assert candidate["content"]["parts"][0] == {"text": "ok"}
    assert candidate["content"]["parts"][1] == {
        "functionCall": {"name": "lookup", "args": {"q": "ping"}}
    }
    assert candidate["finishReason"] == "STOP"


def test_gemini_stream_message_end_includes_usage_metadata():
    payload = normalized_stream_event_to_gemini_chunk(
        NormalizedStreamEvent(
            type="message_end",
            id="req-1",
            model="gemini-pro",
            finish_reason="stop",
            usage=NormalizedUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        ),
        requested_model="gemini-pro",
        response_id="fallback",
    )

    assert payload["candidates"][0]["finishReason"] == "STOP"
    assert payload["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 3,
        "totalTokenCount": 5,
    }
