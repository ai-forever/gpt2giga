"""Keep provider conversation state separate from public function-call IDs."""

import copy
import json
from types import SimpleNamespace

import pytest
from anthropic.lib.streaming._messages import accumulate_event
from anthropic.types import ToolUseBlock
from openai.lib.streaming.chat._completions import ChatCompletionStreamState
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessage
from openai.types.responses import ResponseFunctionToolCall

from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocol.response.gigachat_chat_completion_adapter import (
    adapt_chat_completion_chunk_to_chat_chunk_shape,
)
from gpt2giga.protocols.anthropic import (
    AnthropicProtocolAdapter,
    AnthropicStreamProjector,
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedStreamEvent,
    NormalizedToolCall,
)
from gpt2giga.protocols.openai import (
    OpenAIProtocolAdapter,
    normalized_stream_event_to_openai_chunk,
)
from gpt2giga.protocols.openai.response_adapter import (
    normalized_chat_response_to_openai,
    normalized_chat_response_to_responses,
)
from gpt2giga.protocols.openai.responses_streaming import ResponsesStreamProjector
from gpt2giga.providers.gigachat.adapter import (
    gigachat_response_to_normalized,
    normalized_chat_to_openai_payload,
)
from gpt2giga.providers.gigachat.streaming import GigaChatNormalizedStreamMapper


def _response(state_id, call_count):
    calls = [
        {"id": f"call_{index}", "name": "lookup", "arguments": {"index": index}}
        for index in range(call_count)
    ]
    message = {"role": "assistant", "content": None, "functions_state_id": state_id}
    if call_count == 1:
        message["function_call"] = calls[0]
    else:
        message["tool_calls"] = [
            {"id": call["id"], "type": "function", "function": call} for call in calls
        ]
    raw = {"choices": [{"message": message, "finish_reason": "function_call"}]}
    return gigachat_response_to_normalized(
        SimpleNamespace(model_dump=lambda: copy.deepcopy(raw)),
        request=NormalizedChatRequest(model="test"),
    )


@pytest.mark.parametrize("facade", ["openai", "anthropic", "responses"])
@pytest.mark.parametrize("call_count", [1, 2])
@pytest.mark.parametrize("state_id", ["state-original", "fc_state", "call_state"])
def test_normalized_tool_state_survives_sdk_replay(facade, call_count, state_id):
    response = _response(state_id, call_count)
    if facade == "openai":
        reply = normalized_chat_response_to_openai(response, requested_model="test")
        message = ChatCompletionMessage.model_validate(
            reply["choices"][0]["message"]
        ).model_dump(exclude_none=True)
        request = OpenAIProtocolAdapter().chat_to_normalized(
            {
                "model": "test",
                "messages": [
                    message,
                    *[
                        {"role": "tool", "tool_call_id": call["id"], "content": "{}"}
                        for call in reversed(message["tool_calls"])
                    ],
                ],
            }
        )
    elif facade == "anthropic":
        reply = normalized_chat_response_to_anthropic(response, requested_model="test")
        content = [
            ToolUseBlock.model_validate(block).model_dump(exclude_none=True)
            for block in reply["content"]
        ]
        request = AnthropicProtocolAdapter().messages_to_normalized(
            {
                "model": "test",
                "max_tokens": 64,
                "messages": [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": call["id"],
                                "content": "{}",
                            }
                            for call in reversed(content)
                        ],
                    },
                ],
            }
        )
    else:
        reply = normalized_chat_response_to_responses(
            response, requested_model="test", request_payload={}, response_id="test"
        )
        output = [
            ResponseFunctionToolCall.model_validate(item).model_dump(exclude_none=True)
            for item in reply["output"]
        ]
        request = OpenAIProtocolAdapter().responses_to_normalized(
            {
                "model": "test",
                "input": output
                + [
                    {
                        "type": "function_call_output",
                        "call_id": item["call_id"],
                        "output": "{}",
                    }
                    for item in reversed(output)
                ],
            }
        )
    payload = normalized_chat_to_openai_payload(request)
    calls = [
        call
        for message in payload["messages"]
        for call in message.get("tool_calls", [])
    ]
    assert [call["id"] for call in calls] == [
        f"call_{index}" for index in range(call_count)
    ]
    assert [call.get("tools_state_id") for call in calls] == [state_id] * call_count
    assert [
        message["tool_call_id"]
        for message in payload["messages"]
        if message["role"] == "tool"
    ] == [f"call_{index}" for index in reversed(range(call_count))]


def _events():
    return [
        NormalizedStreamEvent(type="message_start", id="test"),
        NormalizedStreamEvent(
            type="tool_call_start",
            tool_call=NormalizedToolCall(
                id="call_0",
                name="lookup",
                arguments='{"index":',
                raw_extensions={"tools_state_id": "fc_state"},
            ),
        ),
        NormalizedStreamEvent(
            type="tool_call_delta",
            tool_call=NormalizedToolCall(
                arguments="0}",
                raw_extensions={"tools_state_id": "fc_state"},
            ),
        ),
        NormalizedStreamEvent(type="message_end", finish_reason="tool_calls"),
    ]


def test_openai_sdk_stream_accumulates_tool_state_once():
    accumulator = ChatCompletionStreamState()
    chunks = [
        normalized_stream_event_to_openai_chunk(
            event, requested_model="test", response_id="test"
        )
        for event in _events()
    ]
    for chunk in chunks:
        if chunk is not None:
            list(accumulator.handle_chunk(ChatCompletionChunk.model_validate(chunk)))
    call = (
        accumulator.get_final_completion().choices[0].message.tool_calls[0].model_dump()
    )
    assert call["id"] == "call_0"
    assert call["function"]["arguments"] == '{"index":0}'
    assert call.get("tools_state_id") == "fc_state"


def test_gigachat_mapper_deduplicates_tool_identity_for_openai_sdk():
    mapper = GigaChatNormalizedStreamMapper(
        response_processor=SimpleNamespace(
            process_stream_chunk=lambda chunk, *args, **kwargs: copy.deepcopy(chunk)
        ),
        requested_model="test",
        response_id="test",
    )
    accumulator = ChatCompletionStreamState()
    events = []
    for index, arguments in enumerate(['{"index":', "0}"]):
        event = mapper.chunk_to_event(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_0",
                                    "type": "function",
                                    "tools_state_id": "fc_state",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": arguments,
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls" if index else None,
                    }
                ],
            }
        )
        events.append(event)
        chunk = normalized_stream_event_to_openai_chunk(
            event, requested_model="test", response_id="test"
        )
        list(accumulator.handle_chunk(ChatCompletionChunk.model_validate(chunk)))
    assert [event.type for event in events] == ["tool_call_start", "tool_call_delta"]
    assert [event.tool_call.id for event in events] == ["call_0", "call_0"]
    call = (
        accumulator.get_final_completion().choices[0].message.tool_calls[0].model_dump()
    )
    assert call["id"] == "call_0"
    assert call["function"] == {
        "name": "lookup",
        "arguments": '{"index":0}',
        "parsed_arguments": None,
    }
    assert call["tools_state_id"] == "fc_state"


def test_anthropic_sdk_stream_preserves_tool_state():
    projector = AnthropicStreamProjector(requested_model="test", response_id="test")
    snapshot = None
    for event in _events():
        for frame in projector.project(event):
            payload = json.loads(frame.split("data: ", 1)[1])
            if payload["type"] != "ping":
                snapshot = accumulate_event(event=payload, current_snapshot=snapshot)
    block = snapshot.content[0].model_dump()
    assert block["id"] == "call_0"
    assert block["input"] == {"index": 0}
    assert block.get("tools_state_id") == "fc_state"


def test_responses_stream_function_call_replays_with_tool_state():
    projector = ResponsesStreamProjector(
        request_payload={}, requested_model="test", response_id="test"
    )
    frames = [frame for event in _events() for frame in projector.project(event)]
    completed = next(
        json.loads(frame.split("data: ", 1)[1])["response"]
        for frame in frames
        if frame.startswith("event: response.completed\n")
    )
    item = completed["output"][0]
    assert item["call_id"] == "call_0"
    assert item.get("tools_state_id") == "fc_state"
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        {"model": "test", "input": [item]}
    )
    assert (
        normalized.messages[0].tool_calls[0].raw_extensions["tools_state_id"]
        == "fc_state"
    )


def test_responses_tool_result_accepts_explicit_state_without_call_history():
    request = OpenAIProtocolAdapter().responses_to_normalized(
        {
            "model": "test",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_0",
                    "output": "{}",
                    "tools_state_id": "call_state",
                }
            ],
        }
    )
    message = normalized_chat_to_openai_payload(request)["messages"][0]
    assert message["tool_call_id"] == "call_0"
    assert message["tools_state_id"] == "call_state"


def _adapted_chunk(payload):
    adapted = adapt_chat_completion_chunk_to_chat_chunk_shape(
        payload, default_model="test"
    )
    return SimpleNamespace(model_dump=lambda: copy.deepcopy(adapted))


@pytest.mark.parametrize("facade", ["openai", "anthropic", "responses"])
@pytest.mark.parametrize("state_id", ["fc_terminal-state", None])
@pytest.mark.parametrize("chunk_layout", ["together", "separate"])
def test_gigachat_stream_defers_tool_projection_until_state_or_end(
    facade, state_id, chunk_layout
):
    mapper = GigaChatNormalizedStreamMapper(
        response_processor=ResponseProcessor(),
        requested_model="test",
        response_id="test",
    )
    events = [mapper.message_start()]
    parts = [
        {
            "function_call": {
                "id": f"call_{index}",
                "name": "lookup",
                "arguments": {"index": index},
            }
        }
        for index in range(2)
    ]
    chunks = [parts] if chunk_layout == "together" else [[part] for part in parts]
    for content in chunks:
        assert (
            mapper.chunk_to_events(
                _adapted_chunk(
                    {
                        "messages": [{"role": "assistant", "content": content}],
                    }
                )
            )
            == []
        )
    done_message = {"role": "assistant"}
    if state_id is not None:
        done_message["tools_state_id"] = state_id
    events.extend(
        mapper.chunk_to_events(
            _adapted_chunk(
                {
                    "event": "response.message.done",
                    "messages": [done_message],
                    "finish_reason": "function_call",
                }
            )
        )
    )
    events.extend(mapper.flush_tool_events())
    calls = [event.tool_call for event in events if event.tool_call is not None]
    assert [call.id for call in calls] == ["call_0", "call_1"]
    assert [call.raw_extensions.get("tools_state_id") for call in calls] == [
        state_id,
        state_id,
    ]
    if facade == "openai":
        accumulator = ChatCompletionStreamState()
        for event in events:
            chunk = normalized_stream_event_to_openai_chunk(
                event, requested_model="test", response_id="test"
            )
            if chunk is not None:
                list(
                    accumulator.handle_chunk(ChatCompletionChunk.model_validate(chunk))
                )
        message = accumulator.get_final_completion().choices[0].message
        assert message.role == "assistant"
        public_calls = [call.model_dump() for call in message.tool_calls]
    elif facade == "anthropic":
        projector = AnthropicStreamProjector(requested_model="test", response_id="test")
        snapshot = None
        for event in events:
            for frame in projector.project(event):
                payload = json.loads(frame.split("data: ", 1)[1])
                if payload["type"] != "ping":
                    snapshot = accumulate_event(
                        event=payload, current_snapshot=snapshot
                    )
        public_calls = [block.model_dump() for block in snapshot.content]
    else:
        projector = ResponsesStreamProjector(
            request_payload={}, requested_model="test", response_id="test"
        )
        frames = [frame for event in events for frame in projector.project(event)]
        public_calls = next(
            json.loads(frame.split("data: ", 1)[1])["response"]["output"]
            for frame in frames
            if frame.startswith("event: response.completed\n")
        )
    assert [call.get("tools_state_id") for call in public_calls] == [state_id, state_id]
    assert [call.get("call_id", call.get("id")) for call in public_calls] == [
        "call_0",
        "call_1",
    ]


def test_gigachat_stream_assigns_distinct_indexes_to_separate_same_name_calls():
    mapper = GigaChatNormalizedStreamMapper(
        response_processor=ResponseProcessor(),
        requested_model="test",
        response_id="test",
    )
    accumulator = ChatCompletionStreamState()
    for index in range(2):
        events = mapper.chunk_to_events(
            _adapted_chunk(
                {
                    "messages": [
                        {
                            "role": "assistant",
                            "tools_state_id": "fc_state",
                            "content": [
                                {
                                    "function_call": {
                                        "id": f"call_{index}",
                                        "name": "lookup",
                                        "arguments": {"index": index},
                                    }
                                }
                            ],
                        }
                    ],
                    "finish_reason": "function_call" if index else None,
                }
            )
        )
        assert len(events) == 1
        assert events[0].tool_call.raw_extensions["index"] == index
        chunk = normalized_stream_event_to_openai_chunk(
            events[0], requested_model="test", response_id="test"
        )
        list(accumulator.handle_chunk(ChatCompletionChunk.model_validate(chunk)))
    message = accumulator.get_final_completion().choices[0].message
    calls = [call.model_dump() for call in message.tool_calls]
    assert message.role == "assistant"
    assert [call["id"] for call in calls] == ["call_0", "call_1"]
    assert [call["function"]["name"] for call in calls] == ["lookup", "lookup"]
    assert [json.loads(call["function"]["arguments"]) for call in calls] == [
        {"index": 0},
        {"index": 1},
    ]
    assert [call["tools_state_id"] for call in calls] == ["fc_state", "fc_state"]


def test_gigachat_stream_remembers_state_before_the_tool_call():
    mapper = GigaChatNormalizedStreamMapper(
        response_processor=ResponseProcessor(),
        requested_model="test",
        response_id="test",
    )
    events = mapper.chunk_to_events(
        _adapted_chunk(
            {
                "messages": [
                    {"role": "assistant", "tools_state_id": "call_initial-state"}
                ],
            }
        )
    )
    assert events[0].type == "heartbeat"
    assert (
        normalized_stream_event_to_openai_chunk(
            events[0], requested_model="test", response_id="test"
        )
        is None
    )
    events.extend(
        mapper.chunk_to_events(
            _adapted_chunk(
                {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "function_call": {
                                        "id": "call_0",
                                        "name": "lookup",
                                        "arguments": {},
                                    }
                                }
                            ],
                        }
                    ],
                    "finish_reason": "function_call",
                }
            )
        )
    )
    accumulator = ChatCompletionStreamState()
    for event in events:
        chunk = normalized_stream_event_to_openai_chunk(
            event, requested_model="test", response_id="test"
        )
        if chunk is not None:
            list(accumulator.handle_chunk(ChatCompletionChunk.model_validate(chunk)))
    message = accumulator.get_final_completion().choices[0].message
    assert message.role == "assistant"
    assert message.tool_calls[0].id == "call_0"
    assert message.tool_calls[0].model_dump()["tools_state_id"] == "call_initial-state"
