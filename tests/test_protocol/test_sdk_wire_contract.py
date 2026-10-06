"""Hermetic wire contracts crossing gateway transformations and the real SDK."""

import json
from types import SimpleNamespace

import httpx
import pytest
from loguru import logger

from gpt2giga.models.config import GigaChatCLI, ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.protocol.response import adapt_chat_completion_chunk_to_chat_chunk_shape
from gpt2giga.providers.gigachat.client import build_gigachat_client
from gpt2giga.providers.gigachat.model_resolution import resolve_upstream_model


@pytest.fixture
def sdk_wire(monkeypatch):
    """Capture SDK HTTP calls without opening a network connection."""
    for key in ("CREDENTIALS", "USER", "PASSWORD"):
        monkeypatch.delenv(f"GIGACHAT_{key}", raising=False)
    seen = []
    replies = []
    original_client = httpx.AsyncClient

    def handle(request):
        seen.append(request)
        return replies.pop(0)

    def mocked_client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(httpx, "AsyncClient", mocked_client)
    settings = GigaChatCLI(
        base_url="https://gigachat.test/v1",
        model="test-model",
        access_token="fixture-token",
    )
    return build_gigachat_client(settings), seen, replies


async def test_gateway_v2_request_survives_sdk_wire_serialization(sdk_wire):
    client, seen, replies = sdk_wire
    replies.append(
        httpx.Response(200, json={"messages": [{"role": "assistant", "content": "ok"}]})
    )
    transformer = RequestTransformer(
        ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2")), logger=logger
    )
    payload = await transformer.prepare_chat_completion(
        {
            "model": "test-model",
            "temperature": 0.4,
            "max_completion_tokens": 64,
            "tools": [
                {"type": "function", "function": {"name": "lookup", "parameters": {}}}
            ],
            "tool_choice": {"type": "function", "function": {"name": "lookup"}},
            "additional_fields": {
                "model_options": {"temperature": 0.9, "future_option": True},
                "future_request_option": "kept",
            },
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": "state-fixture",
                    "tool_calls": [
                        {
                            "id": f"call_room-{i}",
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "arguments": json.dumps({"room": i}),
                            },
                        }
                        for i in range(2)
                    ],
                },
                *[
                    {
                        "role": "tool",
                        "tool_call_id": f"call_room-{i}",
                        "content": json.dumps({"room": i}),
                    }
                    for i in (1, 0)
                ],
            ],
        }
    )
    async with client:
        await client.achat.create(payload)

    assert len(seen) == 1
    assert seen[0].url.path == "/v2/chat/completions"
    body = json.loads(seen[0].content)
    assert "additional_fields" not in body
    assert "max_tokens" not in body
    assert body["model_options"]["max_tokens"] == 64
    assert body["model_options"]["temperature"] == 0.4
    assert body["model_options"]["future_option"] is True
    assert body["future_request_option"] == "kept"
    assert body["tool_config"] == {"mode": "forced", "function_name": "lookup"}
    parts = [part for message in body["messages"] for part in message["content"]]
    assert [
        part["function_call"]["id"] for part in parts if "function_call" in part
    ] == [
        "call_room-0",
        "call_room-1",
    ]
    results = [part["function_result"] for part in parts if "function_result" in part]
    assert [(item["id"], item["result"]["room"]) for item in results] == [
        ("call_room-1", 1),
        ("call_room-0", 0),
    ]
    assert all(
        message["tools_state_id"] == "state-fixture" for message in body["messages"]
    )


async def test_sdk_eventless_sse_reaches_gateway_stream_processor(sdk_wire):
    client, seen, replies = sdk_wire
    chunks = [
        {"messages": [{"role": "assistant", "content": [{"text": "hello"}]}]},
        {
            "finish_reason": "stop",
            "usage": {
                "input_tokens": 2,
                "input_tokens_details": {"cached_tokens": 3},
                "output_tokens": 1,
            },
        },
    ]
    replies.append(
        httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n",
        )
    )
    processor = ResponseProcessor(logger=logger)
    output = []
    async with client:
        async for chunk in client.achat.stream("hello"):
            adapted = adapt_chat_completion_chunk_to_chat_chunk_shape(
                chunk, default_model="test-model"
            )
            output.append(
                processor.process_stream_chunk(
                    SimpleNamespace(model_dump=lambda: adapted),
                    "test-model",
                    "wire-fixture",
                )
            )

    assert json.loads(seen[0].content)["stream"] is True
    assert len(output) == 2
    assert output[0]["choices"][0]["delta"]["content"] == "hello"
    assert output[1]["choices"][0]["finish_reason"] == "stop"
    assert output[1]["usage"]["prompt_tokens"] == 5
    assert output[1]["usage"]["prompt_tokens_details"]["cached_tokens"] == 3


@pytest.mark.parametrize(
    ("selector", "limiter_key"),
    [
        ({"assistant_id": "assistant-1"}, "assistant:assistant-1"),
        (
            {"storage": {"is_stateful": True, "assistant_id": "assistant-1"}},
            "assistant:assistant-1",
        ),
        (
            {"storage": {"is_stateful": True, "thread_id": "thread-1"}},
            "thread:thread-1",
        ),
    ],
)
async def test_v1_state_selector_survives_sdk_without_injected_model(
    sdk_wire, selector, limiter_key
):
    client, seen, replies = sdk_wire
    replies.append(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
                "created": 1,
                "model": "assistant-model",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )
    )
    config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v1"),
        gigachat={"model": "configured-model"},
    )
    original = {
        "model": "display-model",
        "messages": [{"role": "user", "content": "hello"}],
        "extra_body": selector,
    }
    payload = await RequestTransformer(config, logger=logger).prepare_chat(original)
    resolved = resolve_upstream_model(payload, config, api_mode="v1")
    assert resolved.model is None
    assert resolved.limiter_key == limiter_key
    assert original["model"] == "display-model"
    assert "model" not in payload

    async with client:
        await client.achat(payload)

    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/chat/completions"
    assert "model" not in body
    for key, value in selector.items():
        assert body[key] == value


async def test_v2_assistant_selector_survives_sdk_without_injected_model(sdk_wire):
    client, seen, replies = sdk_wire
    replies.append(
        httpx.Response(200, json={"messages": [{"role": "assistant", "content": "ok"}]})
    )
    config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v2"),
        gigachat={"model": "configured-model"},
    )
    payload = await RequestTransformer(config, logger=logger).prepare_chat_completion(
        {
            "model": "display-model",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {"assistant_id": "assistant-1"},
        }
    )
    resolved = resolve_upstream_model(payload, config, api_mode="v2")
    assert resolved.model is None
    assert resolved.limiter_key == "assistant:assistant-1"
    async with client:
        await client.achat.create(payload)
    body = json.loads(seen[0].content)
    assert body["assistant_id"] == "assistant-1"
    assert "model" not in body
