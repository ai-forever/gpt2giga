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
