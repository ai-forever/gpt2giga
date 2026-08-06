"""Gemini compatibility contracts across protocol, provider, and stable SDK."""

from __future__ import annotations

import json

import httpx
from gigachat.exceptions import BadRequestError

from gpt2giga.protocols.gemini import (
    GeminiProtocolAdapter,
    normalized_chat_response_to_gemini,
    normalized_stream_event_to_gemini_sse,
)


async def test_generate_tools_results_schema_and_usage_cross_stable_sdk(
    contract_stack,
) -> None:
    stack = contract_stack(
        provider="gemini",
        api_mode="v2",
    )
    public_payload = {
        "systemInstruction": {"parts": [{"text": "Be concise."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Weather in Moscow?"}]},
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "id": "call-1",
                            "name": "weather",
                            "args": {"city": "Moscow"},
                        }
                    }
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "id": "call-1",
                            "name": "weather",
                            "response": {"temperature": 20},
                        }
                    }
                ],
            },
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "weather",
                        "description": "Look up weather.",
                        "parametersJsonSchema": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
        },
    }

    protocol = GeminiProtocolAdapter()
    normalized = protocol.generate_content_to_normalized(
        public_payload,
        model="request-model",
    )
    response = await stack.adapter.chat(normalized)
    projected = normalized_chat_response_to_gemini(
        response,
        requested_model="request-model",
    )

    [(_operation, sdk_payload)] = stack.client.calls
    upstream = sdk_payload.model_dump(exclude_none=True, by_alias=True)
    assert upstream["tools"][0]["functions"]["specifications"][0]["name"] == "weather"
    assert upstream["model_options"]["response_format"]["type"] == "json_schema"
    assert any(
        part.get("function_call", {}).get("name") == "weather"
        for message in upstream["messages"]
        for part in message.get("content", [])
    )
    assert any(message["role"] == "tool" for message in upstream["messages"])
    assert projected["candidates"][0]["content"]["parts"] == [{"text": "stable-v2"}]
    assert projected["candidates"][0]["finishReason"] == "STOP"
    assert projected["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 1,
        "totalTokenCount": 3,
    }


async def test_count_tokens_uses_gemini_normalized_input(contract_stack) -> None:
    stack = contract_stack(provider="gemini", api_mode="v2")
    protocol = GeminiProtocolAdapter()
    normalized = protocol.count_tokens_to_normalized(
        {"contents": [{"role": "user", "parts": [{"text": "count these words"}]}]},
        model="request-model",
    )

    response = await stack.adapter.count_tokens(normalized)

    [(texts, model)] = stack.client.token_calls
    assert texts == ["count these words"]
    assert model == "request-model"
    assert response.input_tokens == 3


async def test_stream_terminal_and_gemini_error_shape(contract_stack) -> None:
    stack = contract_stack(provider="gemini", api_mode="v2")
    protocol = GeminiProtocolAdapter()
    normalized = protocol.generate_content_to_normalized(
        {"contents": [{"role": "user", "parts": [{"text": "Stream"}]}]},
        model="request-model",
        stream=True,
    )

    events = [event async for event in stack.adapter.stream_chat(normalized)]
    frames = [
        frame
        for event in events
        if (
            frame := normalized_stream_event_to_gemini_sse(
                event,
                requested_model="request-model",
                response_id="gemini-contract",
            )
        )
        is not None
    ]
    terminal = json.loads(frames[-1].removeprefix("data: "))
    assert terminal["candidates"][0]["finishReason"] == "STOP"
    assert terminal["usageMetadata"]["totalTokenCount"] == 3

    stack.client.calls.clear()
    stack.client.effective_models.clear()
    stack.client.stream_error = BadRequestError(
        "https://gigachat.test/chat/completions",
        400,
        b'{"message":"bad request"}',
        httpx.Headers(),
    )
    error_events = [event async for event in stack.adapter.stream_chat(normalized)]
    error_frame = normalized_stream_event_to_gemini_sse(
        error_events[-1],
        requested_model="request-model",
        response_id="gemini-contract-error",
    )
    assert error_frame is not None
    assert json.loads(error_frame.removeprefix("data: "))["error"] == {
        "code": "stream_error",
        "message": str(stack.client.stream_error),
        "status": "BadRequestError",
    }
