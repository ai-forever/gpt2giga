"""Anthropic compatibility contracts across protocol, provider, and stable SDK."""

from __future__ import annotations

import httpx
from gigachat.exceptions import BadRequestError

from gpt2giga.protocols.anthropic import (
    AnthropicProtocolAdapter,
    AnthropicStreamProjector,
    normalized_chat_response_to_anthropic,
)


async def test_messages_tools_stop_reason_and_usage_cross_stable_sdk(
    contract_stack,
) -> None:
    stack = contract_stack(provider="anthropic", api_mode="v2")
    public_payload = {
        "model": "request-model",
        "max_tokens": 64,
        "system": "Be concise.",
        "messages": [{"role": "user", "content": "Weather in Moscow?"}],
        "tools": [
            {
                "name": "weather",
                "description": "Look up weather.",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
        "tool_choice": {"type": "tool", "name": "weather"},
    }

    protocol = AnthropicProtocolAdapter()
    normalized = protocol.messages_to_normalized(public_payload)
    response = await stack.adapter.chat(normalized)
    projected = normalized_chat_response_to_anthropic(
        response,
        requested_model=public_payload["model"],
    )

    [(_operation, sdk_payload)] = stack.client.calls
    upstream = sdk_payload.model_dump(exclude_none=True, by_alias=True)
    tool = upstream["tools"][0]["functions"]["specifications"][0]
    assert tool["name"] == "weather"
    assert tool["parameters"]["required"] == ["city"]
    assert upstream["tool_config"] == {
        "mode": "function",
        "function_name": "weather",
    }
    assert projected["type"] == "message"
    assert projected["content"] == [{"type": "text", "text": "stable-v2"}]
    assert projected["stop_reason"] == "end_turn"
    assert projected["usage"] == {"input_tokens": 2, "output_tokens": 1}


async def test_count_tokens_includes_messages_and_tools(contract_stack) -> None:
    stack = contract_stack(provider="anthropic", api_mode="v2")
    protocol = AnthropicProtocolAdapter()
    normalized = protocol.count_tokens_to_normalized(
        {
            "model": "request-model",
            "messages": [{"role": "user", "content": "count these words"}],
            "tools": [
                {
                    "name": "weather",
                    "description": "Look up weather.",
                    "input_schema": {"type": "object"},
                }
            ],
        }
    )

    response = await stack.adapter.count_tokens(normalized)

    [(texts, model)] = stack.client.token_calls
    assert model == "request-model"
    assert texts[0] == "count these words"
    assert any("weather" in text for text in texts)
    assert response.input_tokens >= 3


async def test_stream_sequence_and_anthropic_error_shape(contract_stack) -> None:
    stack = contract_stack(provider="anthropic", api_mode="v2")
    protocol = AnthropicProtocolAdapter()
    normalized = protocol.messages_to_normalized(
        {
            "model": "request-model",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Stream"}],
            "stream": True,
        }
    )
    projector = AnthropicStreamProjector(
        requested_model="request-model",
        response_id="anthropic-contract",
    )

    events = [event async for event in stack.adapter.stream_chat(normalized)]
    frames = [frame for event in events for frame in projector.project(event)]
    event_names = [frame.splitlines()[0] for frame in frames]
    assert event_names == [
        "event: message_start",
        "event: ping",
        "event: content_block_start",
        "event: content_block_delta",
        "event: content_block_stop",
        "event: message_delta",
        "event: message_stop",
    ]
    assert '"stop_reason": "end_turn"' in frames[-2]

    stack.client.calls.clear()
    stack.client.effective_models.clear()
    stack.client.stream_error = BadRequestError(
        "https://gigachat.test/chat/completions",
        400,
        b'{"message":"bad request"}',
        httpx.Headers(),
    )
    error_events = [event async for event in stack.adapter.stream_chat(normalized)]
    error_frames = [
        frame
        for event in error_events
        for frame in AnthropicStreamProjector(
            requested_model="request-model",
            response_id="anthropic-contract-error",
        ).project(event)
        if frame.startswith("event: error")
    ]
    assert len(error_frames) == 1
    assert '"type": "BadRequestError"' in error_frames[0]
    assert '"code": "stream_error"' in error_frames[0]
