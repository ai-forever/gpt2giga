from datetime import datetime, timezone

from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.protocols.openai import (
    normalized_chat_response_to_openai,
    normalized_chat_response_to_responses,
)


def test_normalized_chat_response_to_openai_maps_assistant_usage_and_metadata():
    response = NormalizedResponse(
        id="req-1",
        created_at=datetime.fromtimestamp(100, tz=timezone.utc),
        model="GigaChat",
        provider="gigachat",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(role="assistant", content="hello"),
                finish_reason="stop",
            )
        ],
        usage=NormalizedUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        metadata={"gigachat_x_request_id": "rq-1"},
        provider_metadata={"gigachat": {"gigachat_tool_state_id": "state-1"}},
    )

    payload = normalized_chat_response_to_openai(
        response,
        requested_model="gpt-x",
    )

    assert payload["id"] == "chatcmpl-req-1"
    assert payload["created"] == 100
    assert payload["model"] == "gpt-x"
    assert payload["choices"][0]["message"] == {
        "role": "assistant",
        "content": "hello",
        "refusal": None,
    }
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert payload["usage"]["prompt_tokens"] == 2
    assert payload["usage"]["completion_tokens"] == 3
    assert payload["usage"]["total_tokens"] == 5
    assert payload["metadata"] == {
        "gigachat_x_request_id": "rq-1",
        "gigachat_tool_state_id": "state-1",
    }


def test_normalized_chat_response_to_openai_maps_tool_calls():
    response = NormalizedResponse(
        id="req-2",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        NormalizedToolCall(
                            id="state-1",
                            name="lookup",
                            arguments={"q": "ping"},
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
    )

    payload = normalized_chat_response_to_openai(
        response,
        requested_model="gpt-x",
    )

    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"] == [
        {
            "index": 0,
            "id": "state-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q": "ping"}'},
        }
    ]


def test_normalized_chat_response_to_openai_maps_errors():
    response = NormalizedResponse(
        error=NormalizedError(
            type="invalid_request_error",
            message="bad request",
            param="messages",
            code="invalid_messages",
        )
    )

    payload = normalized_chat_response_to_openai(
        response,
        requested_model="gpt-x",
    )

    assert payload == {
        "error": {
            "message": "bad request",
            "type": "invalid_request_error",
            "param": "messages",
            "code": "invalid_messages",
        }
    }


def test_normalized_chat_response_to_responses_maps_text_tools_usage_and_stop():
    response = NormalizedResponse(
        id="fixture",
        model="upstream-model",
        provider="gigachat",
        choices=[
            NormalizedChoice(
                message=NormalizedMessage(
                    role="assistant",
                    content="The answer is 20 C.",
                    tool_calls=[
                        NormalizedToolCall(
                            id="call_weather",
                            name="weather",
                            arguments={"city": "Moscow"},
                        )
                    ],
                ),
                finish_reason="tool_calls",
                stop_reason="tool_calls",
            )
        ],
        usage=NormalizedUsage(input_tokens=11, output_tokens=7, total_tokens=18),
    )

    payload = normalized_chat_response_to_responses(
        response,
        request_payload={
            "instructions": "Be concise.",
            "model": "bridge/codex-test",
            "text": {"format": {"type": "text"}},
            "tools": [{"type": "function", "name": "weather"}],
        },
        requested_model="bridge/codex-test",
        response_id="fixture",
    )

    assert payload["id"] == "resp_fixture"
    assert payload["model"] == "bridge/codex-test"
    assert payload["status"] == "completed"
    assert payload["instructions"] == "Be concise."
    assert payload["output"][0]["content"][0]["text"] == "The answer is 20 C."
    assert payload["output"][1] == {
        "id": "fc_call_weather",
        "type": "function_call",
        "status": "completed",
        "call_id": "call_weather",
        "name": "weather",
        "arguments": '{"city":"Moscow"}',
    }
    assert payload["usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_normalized_chat_response_to_responses_keeps_partial_usage_honest():
    response = NormalizedResponse(
        choices=[
            NormalizedChoice(
                message=NormalizedMessage(role="assistant", content="partial"),
                finish_reason="length",
                stop_reason="max_tokens",
            )
        ],
        usage=NormalizedUsage(input_tokens=4),
    )

    payload = normalized_chat_response_to_responses(
        response,
        request_payload={"model": "bridge/codex-test", "input": "hello"},
        requested_model="bridge/codex-test",
        response_id="partial",
    )

    assert payload["status"] == "incomplete"
    assert payload["incomplete_details"] == {"reason": "max_output_tokens"}
    assert payload["usage"] == {"input_tokens": 4}
