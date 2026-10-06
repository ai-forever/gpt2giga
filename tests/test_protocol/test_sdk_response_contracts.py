"""Contract regressions for SDK 0.2.4a1 (6e9bb50) and provider cache accounting."""

import copy
import json
from types import SimpleNamespace

import pytest
from gigachat.models import ChatCompletionResponse
from gigachat.models.chat_completions import ChatCompletionChunk

from gpt2giga.protocol.anthropic.response import _build_anthropic_response
from gpt2giga.protocol.response.gigachat_chat_completion_adapter import (
    adapt_chat_completion_to_chat_shape,
    adapt_chat_completion_chunk_to_chat_chunk_shape,
)
from gpt2giga.protocol.response.processor import ResponseProcessor
from gpt2giga.protocols.anthropic.response_adapter import (
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.anthropic.streaming import AnthropicStreamProjector
from gpt2giga.protocols.normalized import NormalizedChatRequest
from gpt2giga.protocols.openai.response_adapter import (
    normalized_chat_response_to_openai,
    normalized_chat_response_to_responses,
)
from gpt2giga.protocols.openai.responses_streaming import ResponsesStreamProjector
from gpt2giga.providers.gigachat.adapter import gigachat_response_to_normalized
from gpt2giga.providers.gigachat.streaming import GigaChatNormalizedStreamMapper


def _raw(*, stream=False, tool=False):
    message = {
        "role": "assistant",
        "content": "ok",
        "id_": "sdk-message",
        "functions_state_id": "shared-state",
        "data_for_context": "sdk-context",
    }
    if tool:
        message["function_call"] = {
            "name": "lookup",
            "arguments": {"q": "x"},
            "id_": "call_native",
        }
    return {
        "choices": [
            {
                "delta" if stream else "message": message,
                "finish_reason": "function_call" if tool else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 14,
            "precached_prompt_tokens": 2430,
            "completion_tokens": 2,
            "total_tokens": 16,
        },
    }


def _wrapper(data):
    return SimpleNamespace(model_dump=lambda: copy.deepcopy(data))


@pytest.mark.parametrize("stream", [False, True])
def test_legacy_openai_cache_and_sdk_metadata_projection(stream):
    processor = ResponseProcessor()
    method = processor.process_stream_chunk if stream else processor.process_response
    result = method(_wrapper(_raw(stream=stream, tool=True)), "test", "response")
    assert result["usage"]["prompt_tokens"] == 2444
    assert result["usage"]["total_tokens"] == 2446
    assert result["usage"]["prompt_tokens_details"]["cached_tokens"] == 2430
    message = result["choices"][0]["delta" if stream else "message"]
    assert message["tool_calls"][0]["id"] == "call_native"
    assert not ({"id_", "data_for_context", "functions_state_id"} & message.keys())


def test_legacy_responses_and_anthropic_usage():
    raw = _raw(tool=True)
    response = ResponseProcessor().process_response_api(
        {}, _wrapper(raw), "test", "response"
    )
    assert response["usage"]["input_tokens"] == 2444
    assert response["usage"]["total_tokens"] == 2446
    assert response["usage"]["input_tokens_details"]["cached_tokens"] == 2430
    assert response["output"][0]["call_id"] == "call_native"
    assert response["store"] is False
    assert response["temperature"] is None
    assert response["top_p"] is None
    anthropic = _build_anthropic_response(raw, "test", "response")
    assert anthropic["usage"] == {
        "input_tokens": 14,
        "output_tokens": 2,
        "cache_read_input_tokens": 2430,
    }
    assert anthropic["content"][-1]["id"] == "call_native"


def test_normalized_usage_preserves_cache_across_public_protocols():
    normalized = gigachat_response_to_normalized(
        _wrapper(_raw()), request=NormalizedChatRequest()
    )
    chat = normalized_chat_response_to_openai(normalized, requested_model="test")
    response = normalized_chat_response_to_responses(
        normalized, requested_model="test", request_payload={}, response_id="test"
    )
    anthropic = normalized_chat_response_to_anthropic(
        normalized, requested_model="test"
    )
    assert chat["usage"]["prompt_tokens"] == 2444
    assert chat["usage"]["total_tokens"] == 2446
    assert response["usage"]["input_tokens_details"]["cached_tokens"] == 2430
    assert response["store"] is False
    assert response["temperature"] is response["top_p"] is None
    assert anthropic["usage"] == {
        "input_tokens": 14,
        "output_tokens": 2,
        "cache_read_input_tokens": 2430,
    }


def test_normalized_stream_usage_does_not_add_cache_twice():
    mapper = GigaChatNormalizedStreamMapper(
        response_processor=ResponseProcessor(),
        requested_model="test",
        response_id="test",
    )
    start_event = mapper.message_start()
    event = mapper.chunk_to_event(_wrapper(_raw(stream=True)))
    assert event.usage.input_tokens == 2444
    anthropic = AnthropicStreamProjector(requested_model="test", response_id="test")
    frames = anthropic.project(event)
    data = json.loads(
        next(
            frame.split("data: ")[1]
            for frame in frames
            if frame.startswith("event: message_delta")
        )
    )
    assert data["usage"] == {
        "input_tokens": 14,
        "output_tokens": 2,
        "cache_read_input_tokens": 2430,
    }
    projector = ResponsesStreamProjector(
        request_payload={}, requested_model="test", response_id="test", created_at=100
    )
    projector.project(start_event)
    frames = projector.project(event)
    completed = json.loads(
        next(
            frame.split("data: ")[1]
            for frame in frames
            if frame.startswith("event: response.completed")
        )
    )["response"]
    assert completed["usage"]["input_tokens"] == 2444
    assert completed["usage"]["input_tokens_details"]["cached_tokens"] == 2430
    assert completed["store"] is False
    assert completed["temperature"] is completed["top_p"] is None


@pytest.mark.parametrize(
    "additional_data", [{"execution_steps": []}, [{"name": "lookup"}]]
)
def test_sdk_v2_additional_data_survives_response_and_sse(additional_data):
    payload = {
        "messages": [{"role": "assistant", "content": [{"text": "ok"}]}],
        "additional_data": additional_data,
        "usage": {
            "input_tokens": 14,
            "output_tokens": 2,
            "total_tokens": 16,
            "input_tokens_details": {"cached_tokens": 2430},
        },
    }
    response = ChatCompletionResponse.model_validate(payload)
    chunk = ChatCompletionChunk.model_validate(
        {**payload, "event": "response.message.done", "finish_reason": "stop"}
    )
    for adapted in [
        adapt_chat_completion_to_chat_shape(response, default_model="test"),
        adapt_chat_completion_chunk_to_chat_chunk_shape(chunk, default_model="test"),
    ]:
        assert (
            json.loads(
                adapted["_gpt2giga_provider_metadata"]["gigachat_additional_data"]
            )
            == additional_data
        )
        assert adapted["usage"]["precached_prompt_tokens"] == 2430


def _parallel_chunk():
    return adapt_chat_completion_chunk_to_chat_chunk_shape(
        ChatCompletionChunk.model_validate(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "tools_state_id": "shared-state",
                        "content": [
                            {
                                "function_call": {
                                    "id": f"call_{index}",
                                    "name": "lookup",
                                    "arguments": {"value": index},
                                }
                            }
                            for index in range(2)
                        ],
                    }
                ],
                "finish_reason": "function_call",
            }
        ),
        default_model="test",
    )


def test_parallel_sdk_calls_survive_normalized_stream_projectors():
    mapper = GigaChatNormalizedStreamMapper(
        response_processor=ResponseProcessor(),
        requested_model="test",
        response_id="test",
    )
    events = [
        mapper.message_start(),
        *mapper.chunk_to_events(_wrapper(_parallel_chunk())),
    ]
    assert [event.tool_call.id for event in events[1:]] == ["call_0", "call_1"]
    assert events[1].finish_reason is None
    assert events[2].metadata["gigachat_tool_state_id"] == "shared-state"
    responses = ResponsesStreamProjector(
        request_payload={}, requested_model="test", response_id="test", created_at=100
    )
    anthropic = AnthropicStreamProjector(requested_model="test", response_id="test")
    response_frames = [frame for event in events for frame in responses.project(event)]
    anthropic_frames = [frame for event in events for frame in anthropic.project(event)]
    output = json.loads(
        next(
            frame.split("data: ")[1]
            for frame in response_frames
            if frame.startswith("event: response.completed")
        )
    )["response"]["output"]
    assert [(item["call_id"], json.loads(item["arguments"])) for item in output] == [
        ("call_0", {"value": 0}),
        ("call_1", {"value": 1}),
    ]
    blocks = [
        json.loads(frame.split("data: ")[1])["content_block"]
        for frame in anthropic_frames
        if frame.startswith("event: content_block_start")
    ]
    assert [block["id"] for block in blocks] == ["call_0", "call_1"]
    assert anthropic_frames[-1].startswith("event: message_stop")


async def test_parallel_sdk_calls_survive_native_anthropic_stream():
    from contextlib import asynccontextmanager
    from gpt2giga.protocol.anthropic.streaming import _stream_anthropic_generator

    @asynccontextmanager
    async def limit(*args, **kwargs):
        yield

    async def disconnected():
        return False

    async def chunks(payload):
        yield _wrapper(_parallel_chunk())

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(logger=None)),
        is_disconnected=disconnected,
    )
    client = SimpleNamespace(astream=chunks)
    frames = [
        frame
        async for frame in _stream_anthropic_generator(
            request,
            "test",
            {},
            "test",
            client,
            model_limiter=SimpleNamespace(limit=limit),
            effective_model="test",
        )
    ]
    blocks = [
        json.loads(frame.split("data: ")[1])["content_block"]
        for frame in frames
        if frame.startswith("event: content_block_start")
    ]
    assert [block["id"] for block in blocks] == ["call_0", "call_1"]
    arguments = [
        json.loads(json.loads(frame.split("data: ")[1])["delta"]["partial_json"])
        for frame in frames
        if frame.startswith("event: content_block_delta")
    ]
    assert arguments == [{"value": 0}, {"value": 1}]
    assert frames[-1].startswith("event: message_stop")
