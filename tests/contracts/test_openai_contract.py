"""OpenAI compatibility contracts across protocol, provider, and stable SDK."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.exceptions import BadRequestError
from loguru import logger

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.protocols.openai import (
    OpenAIProtocolAdapter,
    normalized_chat_response_to_openai,
    normalized_stream_done_sse,
    normalized_stream_event_to_openai_sse,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.routers.openai.responses import router as responses_router


def _dump(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return payload.model_dump(exclude_none=True, by_alias=True)


async def test_chat_tools_schema_and_usage_cross_stable_sdk(contract_stack) -> None:
    stack = contract_stack(
        provider="openai",
        api_mode="v2",
        structured_output_mode="native",
    )
    public_payload = {
        "model": "request-model",
        "messages": [{"role": "user", "content": "Weather in Moscow?"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Look up weather.",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "weather"}},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "forecast",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                    "required": ["summary"],
                },
            },
        },
    }

    normalized = await OpenAIProtocolAdapter().to_normalized(public_payload)
    response = await stack.adapter.chat(normalized)
    projected = normalized_chat_response_to_openai(
        response,
        requested_model=public_payload["model"],
    )

    [(_operation, sdk_payload)] = stack.client.calls
    upstream = _dump(sdk_payload)
    assert sdk_payload.__class__.__module__.startswith("gigachat.models")
    assert upstream["tools"][0]["functions"]["specifications"][0]["name"] == "weather"
    assert upstream["tool_config"] == {
        "mode": "function",
        "function_name": "weather",
    }
    assert upstream["model_options"]["response_format"]["type"] == "json_schema"
    assert projected["object"] == "chat.completion"
    assert projected["choices"][0]["message"]["content"] == "stable-v2"
    assert projected["choices"][0]["finish_reason"] == "stop"
    assert projected["usage"]["prompt_tokens"] == 2
    assert projected["usage"]["completion_tokens"] == 1
    assert projected["usage"]["total_tokens"] == 3


async def test_stream_terminal_error_disconnect_and_cancel_contract(
    contract_stack,
) -> None:
    adapter = OpenAIProtocolAdapter()
    stack = contract_stack(provider="openai", api_mode="v2")
    request = await adapter.to_normalized(
        {
            "model": "request-model",
            "messages": [{"role": "user", "content": "Stream"}],
            "stream": True,
        }
    )

    events = [event async for event in stack.adapter.stream_chat(request)]
    frames = [
        frame
        for event in events
        if (
            frame := normalized_stream_event_to_openai_sse(
                event,
                requested_model="request-model",
                response_id="openai-contract",
            )
        )
        is not None
    ]
    frames.append(normalized_stream_done_sse())
    terminal = json.loads(frames[-2].removeprefix("data: "))
    assert terminal["choices"][0]["finish_reason"] == "stop"
    assert frames[-1] == "data: [DONE]\n\n"

    stack.client.calls.clear()
    stack.client.effective_models.clear()
    stack.client.stream_error = BadRequestError(
        "https://gigachat.test/chat/completions",
        400,
        b'{"message":"bad request"}',
        httpx.Headers(),
    )
    error_events = [event async for event in stack.adapter.stream_chat(request)]
    error_frame = normalized_stream_event_to_openai_sse(
        error_events[-1],
        requested_model="request-model",
        response_id="openai-contract",
    )
    assert error_frame is not None
    assert json.loads(error_frame.removeprefix("data: "))["error"] == {
        "message": str(stack.client.stream_error),
        "type": "BadRequestError",
        "code": "stream_error",
    }

    stack.client.stream_error = None

    async def disconnected() -> bool:
        return True

    disconnected_events = [
        event
        async for event in stack.adapter.stream_chat(
            request,
            is_disconnected=disconnected,
        )
    ]
    assert [event.type for event in disconnected_events] == ["message_start"]

    stack.client.stream_error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        _ = [event async for event in stack.adapter.stream_chat(request)]


def test_responses_route_uses_stable_v2_sdk_shape(stable_sdk_client) -> None:
    app = FastAPI()
    app.include_router(responses_router)
    config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v2"),
        gigachat={"model": "configured-model"},
    )
    stable_sdk_client.configured_model = "configured-model"
    transformer = RequestTransformer(config, logger=logger)
    response_processor = ResponseProcessor(logger=logger)
    model_limiter = ModelConcurrencyLimiter({})
    app.state.config = config
    app.state.gigachat_client = stable_sdk_client
    app.state.request_transformer = transformer
    app.state.response_processor = response_processor
    app.state.model_concurrency_limiter = model_limiter
    app.state.responses_provider_adapter = GigaChatProviderAdapter(
        config=config,
        request_transformer=transformer,
        giga_client=stable_sdk_client,
        model_limiter=model_limiter,
        response_processor=response_processor,
        api_mode="v2",
        forced_model="configured-model",
    )
    app.state.logger = logger

    response = TestClient(app).post(
        "/responses",
        json={"model": "request-model", "input": "Answer briefly."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["model"] == "request-model"
    assert body["output"][0]["content"][0]["text"] == "stable-v2"
    assert body["usage"]["input_tokens"] == 2
    assert body["usage"]["output_tokens"] == 1
    assert body["usage"]["total_tokens"] == 3
    assert "input_tokens_details" not in body["usage"]
    assert "output_tokens_details" not in body["usage"]
    assert stable_sdk_client.calls[0][0] == "v2.chat"
