import json

import pytest

from gpt2giga.protocols.normalized import (
    NormalizedError,
    NormalizedMessage,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.protocols.openai import (
    ResponsesStreamProjector,
    ResponsesStreamProtocolError,
)


def _event_names(frames: list[str]) -> list[str]:
    return [frame.splitlines()[0].removeprefix("event: ") for frame in frames]


def _event_data(frame: str) -> dict:
    return json.loads(frame.splitlines()[1].removeprefix("data: "))


def _projector() -> ResponsesStreamProjector:
    return ResponsesStreamProjector(
        request_payload={
            "input": "hello",
            "model": "bridge/codex-test",
            "stream": True,
        },
        requested_model="bridge/codex-test",
        response_id="fixture",
        created_at=100,
    )


def test_responses_stream_projector_orders_text_lifecycle_and_usage() -> None:
    projector = _projector()
    frames = []
    frames.extend(
        projector.project(
            NormalizedStreamEvent(
                type="message_start",
                sequence=0,
                message=NormalizedMessage(role="assistant", content=""),
            )
        )
    )
    frames.extend(
        projector.project(
            NormalizedStreamEvent(
                type="content_delta",
                sequence=1,
                content_delta="Hel",
            )
        )
    )
    frames.extend(
        projector.project(
            NormalizedStreamEvent(
                type="message_end",
                sequence=2,
                content_delta="lo",
                finish_reason="stop",
                usage=NormalizedUsage(
                    input_tokens=3,
                    output_tokens=1,
                    total_tokens=4,
                ),
            )
        )
    )
    projector.finish()

    assert _event_names(frames) == [
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    completed = _event_data(frames[-1])
    assert completed["response"]["output"][0]["content"][0]["text"] == "Hello"
    assert completed["response"]["usage"] == {
        "input_tokens": 3,
        "output_tokens": 1,
        "total_tokens": 4,
    }


def test_responses_stream_projector_orders_tool_lifecycle() -> None:
    projector = _projector()
    frames = projector.project(NormalizedStreamEvent(type="message_start", sequence=0))
    frames.extend(
        projector.project(
            NormalizedStreamEvent(
                type="tool_call_start",
                sequence=1,
                tool_call=NormalizedToolCall(
                    id="call_weather",
                    name="weather",
                    arguments='{"city":"Moscow"}',
                ),
                finish_reason="tool_calls",
                usage=NormalizedUsage(input_tokens=5, output_tokens=2),
            )
        )
    )
    projector.finish()

    assert _event_names(frames) == [
        "response.created",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    item = _event_data(frames[-2])["item"]
    assert item["call_id"] == "call_weather"
    assert item["arguments"] == '{"city":"Moscow"}'
    assert _event_data(frames[-1])["response"]["usage"] == {
        "input_tokens": 5,
        "output_tokens": 2,
    }


@pytest.mark.parametrize(
    "events",
    [
        [
            NormalizedStreamEvent(type="message_start", sequence=0),
            NormalizedStreamEvent(type="message_start", sequence=1),
        ],
        [
            NormalizedStreamEvent(type="message_start", sequence=0),
            NormalizedStreamEvent(type="message_end", sequence=1),
            NormalizedStreamEvent(type="message_end", sequence=2),
        ],
        [
            NormalizedStreamEvent(type="message_start", sequence=1),
            NormalizedStreamEvent(type="content_delta", sequence=0, content_delta="x"),
        ],
    ],
)
def test_responses_stream_projector_rejects_duplicate_or_reordered_events(
    events: list[NormalizedStreamEvent],
) -> None:
    projector = _projector()

    with pytest.raises(ResponsesStreamProtocolError):
        for event in events:
            projector.project(event)


def test_responses_stream_projector_rejects_unfinished_stream() -> None:
    projector = _projector()
    projector.project(NormalizedStreamEvent(type="message_start", sequence=0))

    with pytest.raises(ResponsesStreamProtocolError, match="terminal"):
        projector.finish()


def test_responses_stream_provider_error_is_terminal_without_completion() -> None:
    projector = _projector()
    frames = projector.project(NormalizedStreamEvent(type="message_start", sequence=0))
    frames.extend(
        projector.project(
            NormalizedStreamEvent(
                type="error",
                sequence=1,
                error=NormalizedError(
                    type="provider_error",
                    message="upstream failed",
                    code="upstream_failure",
                ),
            )
        )
    )
    projector.finish()

    assert _event_names(frames) == ["response.created", "error"]
    assert _event_data(frames[-1])["code"] == "upstream_failure"
