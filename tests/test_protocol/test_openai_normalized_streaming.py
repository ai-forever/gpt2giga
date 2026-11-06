import json

from gpt2giga.protocols.normalized import (
    NormalizedError,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.protocols.openai import (
    normalized_stream_done_sse,
    normalized_stream_event_to_openai_chunk,
    normalized_stream_event_to_openai_sse,
)


def _sse_payload(frame: str) -> dict:
    return json.loads(frame.removeprefix("data: ").strip())


def test_normalized_stream_content_event_maps_to_openai_sse_chunk():
    frame = normalized_stream_event_to_openai_sse(
        NormalizedStreamEvent(
            type="content_delta",
            id="req-1",
            model="GigaChat",
            content_delta="Hi",
        ),
        requested_model="gpt-x",
        response_id="req-1",
    )

    payload = _sse_payload(frame)
    assert payload["id"] == "chatcmpl-req-1"
    assert payload["object"] == "chat.completion.chunk"
    assert payload["model"] == "GigaChat"
    assert payload["choices"][0]["delta"]["content"] == "Hi"


def test_normalized_stream_reasoning_tool_usage_and_error_chunks():
    reasoning = normalized_stream_event_to_openai_chunk(
        NormalizedStreamEvent(type="reasoning_delta", reasoning_delta="Plan"),
        requested_model="gpt-x",
        response_id="req-1",
    )
    tool = normalized_stream_event_to_openai_chunk(
        NormalizedStreamEvent(
            type="tool_call_delta",
            tool_call=NormalizedToolCall(
                id="call-1",
                name="lookup",
                arguments='{"q":"ping"}',
            ),
        ),
        requested_model="gpt-x",
        response_id="req-1",
    )
    usage = normalized_stream_event_to_openai_chunk(
        NormalizedStreamEvent(
            type="usage",
            usage=NormalizedUsage(input_tokens=1, output_tokens=2, total_tokens=3),
        ),
        requested_model="gpt-x",
        response_id="req-1",
    )
    error = normalized_stream_event_to_openai_chunk(
        NormalizedStreamEvent(
            type="error",
            error=NormalizedError(
                type="GigaChatException",
                message="upstream failed",
                code="stream_error",
            ),
        ),
        requested_model="gpt-x",
        response_id="req-1",
    )

    assert reasoning["choices"][0]["delta"]["reasoning_content"] == "Plan"
    assert tool["choices"][0]["delta"]["tool_calls"][0]["function"] == {
        "name": "lookup",
        "arguments": '{"q":"ping"}',
    }
    assert usage["usage"]["total_tokens"] == 3
    assert error["error"]["code"] == "stream_error"
    assert normalized_stream_done_sse().strip() == "data: [DONE]"


def test_normalized_stream_event_prefers_legacy_openai_chunk_extension():
    legacy_chunk = {
        "id": "chatcmpl-legacy",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "legacy-model",
        "choices": [{"index": 0, "delta": {"content": "legacy"}}],
        "usage": None,
    }

    chunk = normalized_stream_event_to_openai_chunk(
        NormalizedStreamEvent(
            type="content_delta",
            raw_extensions={"openai_chunk": legacy_chunk},
        ),
        requested_model="gpt-x",
        response_id="req-1",
    )

    assert chunk is legacy_chunk


def test_normalized_stream_usage_preserves_anthropic_cache_without_legacy_chunk():
    frame = normalized_stream_event_to_openai_sse(
        NormalizedStreamEvent(
            type="usage",
            usage=NormalizedUsage(
                input_tokens=2444,
                output_tokens=2,
                total_tokens=2446,
                provider_metadata={"anthropic": {"cache_read_input_tokens": 2430}},
            ),
        ),
        requested_model="claude-test",
        response_id="cache-fixture",
    )
    usage = _sse_payload(frame)["usage"]
    assert usage["prompt_tokens"] == 2444
    assert usage["total_tokens"] == 2446
    assert usage["prompt_tokens_details"]["cached_tokens"] == 2430


def test_compound_gigachat_delta_keeps_reasoning_text_and_terminal_for_all_facades():
    from types import SimpleNamespace
    from gpt2giga.protocol import ResponseProcessor
    from gpt2giga.providers.gigachat.streaming import GigaChatNormalizedStreamMapper
    from gpt2giga.protocols.anthropic.streaming import AnthropicStreamProjector
    from gpt2giga.protocols.openai import ResponsesStreamProjector

    mapper = GigaChatNormalizedStreamMapper(
        response_processor=ResponseProcessor(),
        requested_model="test",
        response_id="fixture",
    )
    start = mapper.message_start()
    events = mapper.chunk_to_events(
        SimpleNamespace(
            model_dump=lambda: {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": '<think>plan</think>{"answer":1}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            }
        )
    )
    assert len(events) == 1
    event = events[0]
    raw = normalized_stream_event_to_openai_chunk(
        event, requested_model="test", response_id="fixture"
    )
    assert raw["choices"][0]["delta"]["content"] == '{"answer":1}'
    assert raw["choices"][0]["delta"]["reasoning_content"] == "plan"
    assert raw["choices"][0]["finish_reason"] == "stop"
    anthropic = AnthropicStreamProjector(requested_model="test", response_id="fixture")
    anthropic.project(start)
    frames = anthropic.project(event)
    payloads = [json.loads(frame.splitlines()[1][6:]) for frame in frames]
    deltas = [
        payload["delta"]
        for payload in payloads
        if payload["type"] == "content_block_delta"
    ]
    assert deltas == [
        {"type": "thinking_delta", "thinking": "plan"},
        {"type": "text_delta", "text": '{"answer":1}'},
    ]
    assert sum(payload["type"] == "message_stop" for payload in payloads) == 1
    responses = ResponsesStreamProjector(
        request_payload={"model": "test", "reasoning": {"summary": "auto"}},
        requested_model="test",
        response_id="fixture",
    )
    responses.project(start)
    payloads = [
        json.loads(frame.splitlines()[1][6:]) for frame in responses.project(event)
    ]
    completed = next(
        payload["response"]
        for payload in payloads
        if payload["type"] == "response.completed"
    )
    assert completed["output"][0]["summary"][0]["text"] == "plan"
    assert completed["output"][1]["content"][0]["text"] == '{"answer":1}'
