"""Replay native tool responses through the real public client SDK models."""

import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from anthropic.lib.streaming._messages import accumulate_event
from anthropic.types import Message, RawMessageStreamEvent
from gigachat.models import ChatCompletionResponse
from gigachat.models.chat_completions import ChatCompletionChunk as GigaChatChunk
from loguru import logger
from openai.lib.streaming.chat import ChatCompletionStreamState
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import TypeAdapter

from gpt2giga.common.streaming import stream_chat_completion_generator
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)
from gpt2giga.protocol.anthropic.response import _build_anthropic_response
from gpt2giga.protocol.anthropic.streaming import (
    _stream_anthropic_chat_completion_generator,
)
from gpt2giga.protocol.response.gigachat_chat_completion_adapter import (
    adapt_chat_completion_to_chat_shape,
)


MODEL = "GigaChat-2-Max"
OPAQUE_STATES = ["state-original", "fc_state-original", "call_state-original"]


def _provider_payload(state_id, call_count, *, argument_fragment=None):
    return {
        "model": MODEL,
        "messages": [
            {
                "role": "assistant",
                "tools_state_id": state_id,
                "content": [
                    {
                        "function_call": {
                            "id": f"call-{index}",
                            "name": "lookup",
                            "arguments": (
                                argument_fragment(index)
                                if argument_fragment is not None
                                else {"i": index}
                            ),
                        }
                    }
                    for index in range(call_count)
                ],
            }
        ],
        "finish_reason": "function_call",
        "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    }


def _wrapper(payload):
    return SimpleNamespace(model_dump=lambda: copy.deepcopy(payload))


def _terminal_state_chunk(state_id):
    return GigaChatChunk.model_validate(
        {
            "event": "response.message.done",
            "model": MODEL,
            "messages": [
                {"role": "assistant", "tools_state_id": state_id, "content": []}
            ],
            "finish_reason": "function_call",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }
    )


@asynccontextmanager
async def _model_limit(*args, **kwargs):
    yield


async def _disconnected():
    return False


def _stream_request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(logger=None, response_processor=ResponseProcessor())
        ),
        is_disconnected=_disconnected,
    )


def _openai_followup(message):
    calls = message["tool_calls"]
    return {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "lookup"},
            message,
            *[
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(json.loads(call["function"]["arguments"])),
                }
                for call in reversed(calls)
            ],
        ],
    }


def _anthropic_followup(message):
    calls = [block for block in message["content"] if block["type"] == "tool_use"]
    return _build_openai_data_from_anthropic_request(
        {
            "model": MODEL,
            "max_tokens": 64,
            "messages": [
                {"role": "user", "content": "lookup"},
                {"role": "assistant", "content": message["content"]},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": json.dumps(call["input"]),
                        }
                        for call in reversed(calls)
                    ],
                },
            ],
        },
        logger,
    )


async def _assert_v2_replay(payload, *, state_id, call_count, call_ids=None):
    if call_ids is None:
        call_ids = [f"call-{index}" for index in range(call_count)]
    request = await RequestTransformer(
        ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2")), logger=logger
    ).prepare_chat_completion(payload)
    messages = request.model_dump(by_alias=True, exclude_none=True)["messages"]

    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        *["tool"] * call_count,
    ]
    assert [message.get("tools_state_id") for message in messages[1:]] == [state_id] * (
        call_count + 1
    )
    assert [part["function_call"] for part in messages[1]["content"]] == [
        {"id": call_ids[index], "name": "lookup", "arguments": {"i": index}}
        for index in range(call_count)
    ]
    assert [message["content"][0]["function_result"] for message in messages[2:]] == [
        {"id": call_ids[index], "name": "lookup", "result": {"i": index}}
        for index in reversed(range(call_count))
    ]


@pytest.mark.parametrize("facade", ["openai", "anthropic"])
@pytest.mark.parametrize("call_count", [1, 2])
@pytest.mark.parametrize("state_id", OPAQUE_STATES)
async def test_native_tool_state_roundtrip_through_client_sdk(
    facade, call_count, state_id
):
    adapted = adapt_chat_completion_to_chat_shape(
        ChatCompletionResponse.model_validate(_provider_payload(state_id, call_count)),
        default_model=MODEL,
    )
    if facade == "openai":
        response = ResponseProcessor().process_response(
            _wrapper(adapted), MODEL, "roundtrip"
        )
        message = (
            ChatCompletion.model_validate(response)
            .choices[0]
            .message.model_dump(exclude_none=True)
        )
        payload = _openai_followup(message)
    else:
        response = _build_anthropic_response(adapted, MODEL, "roundtrip")
        message = Message.model_validate(response).model_dump(exclude_none=True)
        payload = _anthropic_followup(message)

    await _assert_v2_replay(payload, state_id=state_id, call_count=call_count)


@pytest.mark.parametrize("call_count", [1, 2])
@pytest.mark.parametrize("state_id", OPAQUE_STATES)
@pytest.mark.parametrize(
    "late_state", [False, True], ids=["inline-state", "late-state"]
)
async def test_native_openai_stream_state_survives_sdk_accumulation(
    call_count, state_id, late_state
):
    async def chunks(payload):
        for terminal, argument_fragment in [
            (False, lambda index: '{"i":'),
            (True, lambda index: f"{index}}}"),
        ]:
            provider_payload = _provider_payload(
                state_id, call_count, argument_fragment=argument_fragment
            )
            if late_state:
                provider_payload["messages"][0].pop("tools_state_id")
            if not terminal or late_state:
                provider_payload.pop("finish_reason")
                provider_payload.pop("usage")
            yield GigaChatChunk.model_validate(provider_payload)
        if late_state:
            yield _terminal_state_chunk(state_id)

    accumulator = ChatCompletionStreamState()
    emitted_states = {index: [] for index in range(call_count)}
    async for frame in stream_chat_completion_generator(
        _stream_request(),
        MODEL,
        {},
        "roundtrip",
        SimpleNamespace(achat=SimpleNamespace(stream=chunks)),
        model_limiter=SimpleNamespace(limit=_model_limit),
        effective_model=MODEL,
    ):
        data = frame.split("data: ", 1)[1].strip()
        if data == "[DONE]":
            continue
        response = json.loads(data)
        for call in response["choices"][0]["delta"].get("tool_calls") or []:
            if "tools_state_id" in call:
                emitted_states[call["index"]].append(call["tools_state_id"])
        list(accumulator.handle_chunk(ChatCompletionChunk.model_validate(response)))

    assert emitted_states == {index: [state_id] for index in range(call_count)}
    message = (
        accumulator.get_final_completion()
        .choices[0]
        .message.model_dump(exclude_none=True)
    )
    assert [call["id"] for call in message["tool_calls"]] == [
        f"call-{index}" for index in range(call_count)
    ]
    assert [call["tools_state_id"] for call in message["tool_calls"]] == [
        state_id
    ] * call_count
    await _assert_v2_replay(
        _openai_followup(message), state_id=state_id, call_count=call_count
    )


async def test_native_openai_stream_indexes_calls_across_separate_chunks():
    state_id = "state-original"

    async def chunks(payload):
        for index in range(2):
            provider_payload = _provider_payload(state_id, 2)
            message = provider_payload["messages"][0]
            message["content"] = [message["content"][index]]
            if index == 0:
                provider_payload.pop("finish_reason")
                provider_payload.pop("usage")
            yield GigaChatChunk.model_validate(provider_payload)

    accumulator = ChatCompletionStreamState()
    indexes = []
    async for frame in stream_chat_completion_generator(
        _stream_request(),
        MODEL,
        {},
        "sequential-calls",
        SimpleNamespace(achat=SimpleNamespace(stream=chunks)),
        model_limiter=SimpleNamespace(limit=_model_limit),
        effective_model=MODEL,
    ):
        data = frame.split("data: ", 1)[1].strip()
        if data == "[DONE]":
            continue
        response = json.loads(data)
        indexes.extend(
            call["index"]
            for call in response["choices"][0]["delta"].get("tool_calls") or []
        )
        list(accumulator.handle_chunk(ChatCompletionChunk.model_validate(response)))

    assert indexes == [0, 1]
    message = (
        accumulator.get_final_completion()
        .choices[0]
        .message.model_dump(exclude_none=True)
    )
    assert [call["id"] for call in message["tool_calls"]] == ["call-0", "call-1"]
    await _assert_v2_replay(_openai_followup(message), state_id=state_id, call_count=2)


@pytest.mark.parametrize("call_count", [1, 2])
@pytest.mark.parametrize("state_id", OPAQUE_STATES)
@pytest.mark.parametrize(
    "late_state", [False, True], ids=["inline-state", "late-state"]
)
async def test_native_anthropic_stream_state_survives_sdk_accumulation(
    call_count, state_id, late_state
):
    async def chunks(payload):
        provider_payload = _provider_payload(state_id, call_count)
        if late_state:
            provider_payload["messages"][0].pop("tools_state_id")
            provider_payload.pop("finish_reason")
            provider_payload.pop("usage")
        yield GigaChatChunk.model_validate(provider_payload)
        if late_state:
            yield _terminal_state_chunk(state_id)

    event_adapter = TypeAdapter(RawMessageStreamEvent)
    snapshot = None
    starts = []
    async for frame in _stream_anthropic_chat_completion_generator(
        _stream_request(),
        MODEL,
        {},
        "roundtrip",
        SimpleNamespace(achat=SimpleNamespace(stream=chunks)),
        model_limiter=SimpleNamespace(limit=_model_limit),
        effective_model=MODEL,
    ):
        data = json.loads(frame.split("data: ", 1)[1])
        if data["type"] == "ping":
            continue
        if data["type"] == "content_block_start":
            starts.append(data["content_block"])
        snapshot = accumulate_event(
            event=event_adapter.validate_python(data), current_snapshot=snapshot
        )

    assert [block.get("tools_state_id") for block in starts] == [state_id] * call_count
    assert snapshot is not None
    message = snapshot.model_dump(exclude_none=True)
    await _assert_v2_replay(
        _anthropic_followup(message), state_id=state_id, call_count=call_count
    )


@pytest.mark.parametrize("facade", ["openai", "anthropic"])
async def test_native_stream_preserves_state_received_before_tool_calls(facade):
    state_id = "fc_state-original"
    call_count = 2

    async def chunks(payload):
        yield GigaChatChunk.model_validate(
            {
                "model": MODEL,
                "messages": [{"role": "assistant", "tools_state_id": state_id}],
            }
        )
        provider_payload = _provider_payload(state_id, call_count)
        provider_payload["messages"][0].pop("tools_state_id")
        yield GigaChatChunk.model_validate(provider_payload)

    generator = (
        stream_chat_completion_generator
        if facade == "openai"
        else _stream_anthropic_chat_completion_generator
    )
    accumulator = ChatCompletionStreamState()
    event_adapter = TypeAdapter(RawMessageStreamEvent)
    snapshot = None
    async for frame in generator(
        _stream_request(),
        MODEL,
        {},
        "initial-state",
        SimpleNamespace(achat=SimpleNamespace(stream=chunks)),
        model_limiter=SimpleNamespace(limit=_model_limit),
        effective_model=MODEL,
    ):
        data = frame.split("data: ", 1)[1].strip()
        if data == "[DONE]":
            continue
        event = json.loads(data)
        if facade == "openai":
            list(accumulator.handle_chunk(ChatCompletionChunk.model_validate(event)))
        elif event["type"] != "ping":
            snapshot = accumulate_event(
                event=event_adapter.validate_python(event), current_snapshot=snapshot
            )

    if facade == "openai":
        message = (
            accumulator.get_final_completion()
            .choices[0]
            .message.model_dump(exclude_none=True)
        )
        assert [call.get("tools_state_id") for call in message["tool_calls"]] == [
            state_id
        ] * call_count
        payload = _openai_followup(message)
    else:
        assert snapshot is not None
        message = snapshot.model_dump(exclude_none=True)
        assert [call.get("tools_state_id") for call in message["content"]] == [
            state_id
        ] * call_count
        payload = _anthropic_followup(message)
    await _assert_v2_replay(payload, state_id=state_id, call_count=call_count)


async def test_native_openai_stream_idless_fragments_keep_one_sdk_call():
    state_id = "fc_state-original"

    async def chunks(payload):
        for index, fragment in enumerate(['{"i":', "0}"]):
            provider_payload = _provider_payload(
                state_id, 1, argument_fragment=lambda _: fragment
            )
            message = provider_payload["messages"][0]
            message["content"][0]["function_call"].pop("id")
            if index == 0:
                message.pop("tools_state_id")
                provider_payload.pop("finish_reason")
                provider_payload.pop("usage")
            yield GigaChatChunk.model_validate(provider_payload)

    accumulator = ChatCompletionStreamState()
    async for frame in stream_chat_completion_generator(
        _stream_request(),
        MODEL,
        {},
        "idless-fragments",
        SimpleNamespace(achat=SimpleNamespace(stream=chunks)),
        model_limiter=SimpleNamespace(limit=_model_limit),
        effective_model=MODEL,
    ):
        data = frame.split("data: ", 1)[1].strip()
        if data != "[DONE]":
            list(
                accumulator.handle_chunk(ChatCompletionChunk.model_validate_json(data))
            )

    message = (
        accumulator.get_final_completion()
        .choices[0]
        .message.model_dump(exclude_none=True)
    )
    assert len(message["tool_calls"]) == 1
    call = message["tool_calls"][0]
    assert call["id"]
    assert json.loads(call["function"]["arguments"]) == {"i": 0}
    assert call["tools_state_id"] == state_id
    await _assert_v2_replay(
        _openai_followup(message),
        state_id=state_id,
        call_count=1,
        call_ids=[call["id"]],
    )
