import asyncio
from datetime import datetime, timezone

import pytest
from gigachat.models.chat_completions import ChatCompletionResponse

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.core.context import RequestContext
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedTool,
    NormalizedToolCall,
)
from gpt2giga.providers.gigachat.adapter import (
    GigaChatProviderAdapter,
    normalized_chat_to_openai_payload,
)


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeAChat:
    def __init__(self):
        self.calls = []
        self.create_calls = []

    async def __call__(self, payload):
        self.calls.append(payload)
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            }
        )

    async def create(self, payload):
        self.create_calls.append(payload)
        return ChatCompletionResponse.model_validate(
            {
                "model": "GigaChat",
                "messages": [{"role": "assistant", "content": [{"text": "ok-v2"}]}],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 4,
                    "output_tokens": 5,
                    "total_tokens": 9,
                },
            }
        )


class FakeClient:
    def __init__(self):
        self.achat = FakeAChat()


class FakeTransformer:
    def __init__(self):
        self.calls = []
        self.chat_completion_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.calls.append((data, giga_client))
        return {"model": data["model"], "messages": data["messages"]}

    async def prepare_chat_completion(self, data, giga_client=None):
        self.chat_completion_calls.append((data, giga_client))
        return {"model": data["model"], "messages": data["messages"]}


def test_normalized_chat_to_openai_payload_maps_tools_and_generation_config():
    request = NormalizedChatRequest(
        model="GigaChat",
        messages=[
            NormalizedMessage(role="system", content="Be concise."),
            NormalizedMessage(role="user", content="hello"),
            NormalizedMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    NormalizedToolCall(
                        id="call-1",
                        name="lookup",
                        arguments='{"q":"ping"}',
                        raw_extensions={"function": {"extra": "kept"}},
                    )
                ],
            ),
        ],
        response_format=NormalizedResponseFormat(
            type="json_schema",
            json_schema={
                "name": "answer",
                "schema": {"type": "object"},
                "strict": True,
            },
        ),
        tools=[
            NormalizedTool(
                name="lookup",
                description="Lookup data",
                parameters={"type": "object"},
            )
        ],
        provider_metadata={
            "gigachat": {"additional_fields": {"profanity_check": False}}
        },
    )
    request.generation_config.temperature = 0.2
    request.generation_config.max_tokens = 128

    payload = normalized_chat_to_openai_payload(request)

    assert payload["model"] == "GigaChat"
    assert payload["messages"][0] == {
        "role": "system",
        "content": "Be concise.",
    }
    assert payload["messages"][1] == {"role": "user", "content": "hello"}
    assert payload["messages"][2]["tool_calls"][0]["function"] == {
        "name": "lookup",
        "arguments": '{"q":"ping"}',
        "extra": "kept",
    }
    assert payload["response_format"]["json_schema"]["name"] == "answer"
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 128
    assert payload["additional_fields"] == {"profanity_check": False}


@pytest.mark.asyncio
async def test_gigachat_provider_adapter_executes_chat_to_normalized_response():
    client = FakeClient()
    transformer = FakeTransformer()
    adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
        request_transformer=transformer,
        giga_client=client,
        model_limiter=ModelConcurrencyLimiter({}),
    )
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id=None,
        protocol="openai",
        route="/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
    )

    response = await adapter.chat(
        NormalizedChatRequest(
            model="GigaChat",
            messages=[NormalizedMessage(role="user", content="hello")],
        ),
        context=context,
    )

    assert transformer.calls[0][0]["messages"][0]["content"] == "hello"
    assert client.achat.calls[0]["model"] == "GigaChat"
    assert response.id == "req-1"
    assert response.provider == "gigachat"
    assert response.choices[0].message.content == "ok"
    assert response.usage.input_tokens == 2
    assert response.usage.output_tokens == 3


@pytest.mark.asyncio
async def test_gigachat_provider_adapter_executes_chat_completion_to_normalized_response():
    client = FakeClient()
    transformer = FakeTransformer()
    adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2")),
        request_transformer=transformer,
        giga_client=client,
        model_limiter=ModelConcurrencyLimiter({}),
    )

    response = await adapter.chat(
        NormalizedChatRequest(
            model="GigaChat",
            messages=[NormalizedMessage(role="user", content="hello")],
        ),
    )

    assert not transformer.calls
    assert transformer.chat_completion_calls
    assert client.achat.create_calls
    assert response.choices[0].message.content == "ok-v2"
    assert response.usage.input_tokens == 4
    assert response.usage.output_tokens == 5


@pytest.mark.asyncio
async def test_gigachat_provider_adapter_api_mode_override_wins_over_config():
    client = FakeClient()
    transformer = FakeTransformer()
    adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
        request_transformer=transformer,
        giga_client=client,
        model_limiter=ModelConcurrencyLimiter({}),
        api_mode="v2",
    )

    await adapter.chat(
        NormalizedChatRequest(
            model="GigaChat",
            messages=[NormalizedMessage(role="user", content="hello")],
        ),
    )

    assert not transformer.calls
    assert transformer.chat_completion_calls
    assert client.achat.calls == []
    assert client.achat.create_calls


class FakeStreamClient:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or []
        self.error = error
        self.achat = FakeAChatStream(self)

    def astream(self, payload):
        async def gen():
            if self.error is not None:
                raise self.error
            for chunk in self.chunks:
                yield MockResponse(chunk)

        return gen()


class FakeAChatStream:
    def __init__(self, parent):
        self.parent = parent

    def stream(self, payload):
        async def gen():
            if self.parent.error is not None:
                raise self.parent.error
            for chunk in self.parent.chunks:
                yield ChatCompletionResponse.model_validate(chunk)

        return gen()


@pytest.mark.asyncio
async def test_gigachat_provider_adapter_streams_chat_to_normalized_events():
    client = FakeStreamClient(
        chunks=[
            {
                "choices": [{"delta": {"content": "A"}, "finish_reason": None}],
                "usage": None,
            },
            {
                "choices": [{"delta": {"content": "B"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            },
        ]
    )
    adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
        request_transformer=FakeTransformer(),
        giga_client=client,
        model_limiter=ModelConcurrencyLimiter({}),
        response_processor=ResponseProcessor(),
    )

    events = [
        event
        async for event in adapter.stream_chat(
            NormalizedChatRequest(
                model="GigaChat",
                stream=True,
                messages=[NormalizedMessage(role="user", content="hello")],
            ),
            context=RequestContext(
                request_id="req-1",
                trace_id="trace-1",
                span_id=None,
                protocol="openai",
                route="/chat/completions",
                method="POST",
                started_at=datetime.now(timezone.utc),
            ),
        )
    ]

    assert [event.type for event in events] == [
        "message_start",
        "content_delta",
        "message_end",
    ]
    assert events[1].content_delta == "A"
    assert events[2].content_delta == "B"
    assert events[2].finish_reason == "stop"
    assert events[2].usage.total_tokens == 3
    assert (
        events[1].raw_extensions["openai_chunk"]["choices"][0]["delta"]["content"]
        == "A"
    )


@pytest.mark.asyncio
async def test_gigachat_provider_adapter_streams_tool_call_delta():
    client = FakeStreamClient(
        chunks=[
            {
                "choices": [
                    {
                        "delta": {
                            "function_call": {
                                "name": "lookup",
                                "arguments": {"q": "ping"},
                            },
                            "functions_state_id": "state-1",
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": None,
            }
        ]
    )
    adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
        request_transformer=FakeTransformer(),
        giga_client=client,
        model_limiter=ModelConcurrencyLimiter({}),
        response_processor=ResponseProcessor(),
    )

    events = [
        event
        async for event in adapter.stream_chat(
            NormalizedChatRequest(
                model="GigaChat",
                stream=True,
                messages=[NormalizedMessage(role="user", content="hello")],
            )
        )
    ]

    assert events[1].type == "tool_call_start"
    assert events[1].tool_call.id == "state-1"
    assert events[1].tool_call.name == "lookup"
    assert events[1].tool_call.arguments == '{"q": "ping"}'


@pytest.mark.asyncio
async def test_gigachat_provider_adapter_stream_error_event_and_cancellation():
    error_adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
        request_transformer=FakeTransformer(),
        giga_client=FakeStreamClient(error=RuntimeError("boom")),
        model_limiter=ModelConcurrencyLimiter({}),
        response_processor=ResponseProcessor(),
    )

    events = [
        event
        async for event in error_adapter.stream_chat(
            NormalizedChatRequest(
                model="GigaChat",
                stream=True,
                messages=[NormalizedMessage(role="user", content="hello")],
            )
        )
    ]

    assert [event.type for event in events] == ["message_start", "error"]
    assert events[-1].error.type == "RuntimeError"
    assert events[-1].error.message == "Stream interrupted"

    cancel_adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
        request_transformer=FakeTransformer(),
        giga_client=FakeStreamClient(error=asyncio.CancelledError()),
        model_limiter=ModelConcurrencyLimiter({}),
        response_processor=ResponseProcessor(),
    )
    stream = cancel_adapter.stream_chat(
        NormalizedChatRequest(
            model="GigaChat",
            stream=True,
            messages=[NormalizedMessage(role="user", content="hello")],
        )
    )

    assert (await anext(stream)).type == "message_start"
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)


@pytest.mark.asyncio
async def test_gigachat_provider_adapter_stream_disconnect_stops_after_start():
    adapter = GigaChatProviderAdapter(
        config=ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1")),
        request_transformer=FakeTransformer(),
        giga_client=FakeStreamClient(
            chunks=[
                {
                    "choices": [{"delta": {"content": "A"}, "finish_reason": None}],
                    "usage": None,
                }
            ]
        ),
        model_limiter=ModelConcurrencyLimiter({}),
        response_processor=ResponseProcessor(),
    )

    async def disconnected():
        return True

    events = [
        event
        async for event in adapter.stream_chat(
            NormalizedChatRequest(
                model="GigaChat",
                stream=True,
                messages=[NormalizedMessage(role="user", content="hello")],
            ),
            is_disconnected=disconnected,
        )
    ]

    assert [event.type for event in events] == ["message_start"]
