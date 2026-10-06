import json
from types import SimpleNamespace

import pytest
from loguru import logger

from gpt2giga.protocol.response.processor import ResponseProcessor
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
)
from gpt2giga.protocols.openai import (
    ResponsesStreamProjector,
    normalized_chat_response_to_responses,
)


@pytest.mark.parametrize(
    "options, expected",
    [
        ({}, False),
        ({"parallel_tool_calls": True}, True),
        ({"parallel_tool_calls": False}, False),
        ({"parallel_tool_calls": None}, False),
    ],
)
def test_native_responses_parallel_tool_calls_echo(options, expected):
    response = ResponseProcessor(logger=logger).process_response_api(
        options,
        SimpleNamespace(
            model_dump=lambda: {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
        "GigaChat-2-Max",
        "fixture",
    )

    assert response["parallel_tool_calls"] is expected


@pytest.mark.parametrize(
    "provider, default",
    [("gigachat", False), ("openai_compatible", True), ("anthropic", True)],
)
@pytest.mark.parametrize(
    "options",
    [
        {},
        {"parallel_tool_calls": True},
        {"parallel_tool_calls": False},
        {"parallel_tool_calls": None},
    ],
)
def test_normalized_responses_parallel_tool_calls_echo(provider, default, options):
    response = NormalizedResponse(
        provider=provider,
        choices=[
            NormalizedChoice(
                message=NormalizedMessage(role="assistant", content="ok"),
                finish_reason="stop",
            )
        ],
    )
    result = normalized_chat_response_to_responses(
        response,
        request_payload=options,
        requested_model="bridge/model",
        response_id="fixture",
    )

    expected = options.get("parallel_tool_calls")
    assert result["parallel_tool_calls"] is (default if expected is None else expected)


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize(
    "options",
    [
        {},
        {"parallel_tool_calls": True},
        {"parallel_tool_calls": False},
        {"parallel_tool_calls": None},
    ],
)
def test_normalized_stream_parallel_tool_calls_echo(default, options):
    projector = ResponsesStreamProjector(
        request_payload=options,
        requested_model="bridge/model",
        response_id="fixture",
        default_parallel_tool_calls=default,
    )
    frames = projector.project(NormalizedStreamEvent(type="message_start", sequence=0))
    frames.extend(
        projector.project(
            NormalizedStreamEvent(type="message_end", sequence=1, finish_reason="stop")
        )
    )
    projector.finish()

    expected = options.get("parallel_tool_calls")
    responses = [
        json.loads(frame.splitlines()[1].removeprefix("data: "))["response"]
        for frame in frames
        if frame.startswith(
            ("event: response.created\n", "event: response.completed\n")
        )
    ]
    assert len(responses) == 2
    assert all(
        response["parallel_tool_calls"] is (default if expected is None else expected)
        for response in responses
    )
