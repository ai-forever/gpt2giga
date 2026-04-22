import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import gigachat.exceptions
import pytest
from loguru import logger

from gpt2giga.api.openai.streaming import (
    format_chat_stream_chunk as transport_format_chat_stream_chunk,
)
from gpt2giga.api.openai.streaming import (
    format_chat_stream_done as transport_format_chat_stream_done,
)
from gpt2giga.api.openai.streaming import (
    format_responses_stream_event as transport_format_responses_stream_event,
)
from gpt2giga.core.http.sse import (
    format_chat_stream_chunk,
    format_chat_stream_done,
    format_responses_stream_event,
)
from gpt2giga.app.dependencies import RuntimeProviders
from gpt2giga.features.chat.stream import stream_chat_completion_generator
from gpt2giga.features.responses.stream import (
    ResponsesStreamEventSequencer,
)
from gpt2giga.features.responses.stream import (
    stream_responses_generator,
)
from gpt2giga.providers.gigachat import GigaChatChatMapper, ResponseProcessor


def make_chunk(data):
    return SimpleNamespace(model_dump=lambda *args, **kwargs: data)


class FakeClient:
    def astream(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "choices": [{"delta": {"content": "A"}}],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield make_chunk(
                {
                    "choices": [{"delta": {"content": "B"}}],
                    "usage": None,
                    "model": "giga",
                }
            )

        return gen()


class FakeResponsesClient:
    def astream_v2(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "A"}],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "B"}],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 1},
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()


class FakeResponsesClientLegacy:
    def astream(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "choices": [{"delta": {"role": "assistant", "content": "A"}}],
                    "usage": None,
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "B"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()


class FakeClientError:
    def astream(self, chat):
        async def gen():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        return gen()

    def astream_v2(self, chat):
        async def gen():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        return gen()


class FakeClientGigaChatError:
    def astream(self, chat):
        async def gen():
            exc = gigachat.exceptions.GigaChatException("GigaChat API error occurred")
            exc.status_code = 403
            raise exc
            yield  # pragma: no cover

        return gen()

    def astream_v2(self, chat):
        async def gen():
            exc = gigachat.exceptions.GigaChatException("GigaChat API error occurred")
            exc.status_code = 403
            raise exc
            yield  # pragma: no cover

        return gen()


class FakeClientCancelled:
    def astream(self, chat):
        async def gen():
            raise asyncio.CancelledError()
            yield  # pragma: no cover

        return gen()

    def astream_v2(self, chat):
        async def gen():
            raise asyncio.CancelledError()
            yield  # pragma: no cover

        return gen()


class FakeAppState:
    def __init__(self, client, logger_=None):
        response_processor = ResponseProcessor(logger=logger or logger_)
        self.providers = RuntimeProviders(
            gigachat_client=client,
            response_processor=response_processor,
        )
        self.rquid = "rquid-1"
        self.logger = logger_


class FakeRequest:
    def __init__(self, client, disconnected: bool = False, logger_=None):
        self.app = SimpleNamespace(state=FakeAppState(client, logger_))
        self._disconnected = disconnected

    async def is_disconnected(self):
        return self._disconnected


def make_chat_mapper(logger_=None):
    return GigaChatChatMapper(
        response_processor=ResponseProcessor(logger=logger or logger_)
    )


def parse_sse(line):
    parts = line.strip().split("\n")
    event_type = parts[0].replace("event: ", "")
    data = json.loads(parts[1].replace("data: ", ""))
    return event_type, data


def test_openai_streaming_facade_reexports_core_sse_helpers():
    assert transport_format_chat_stream_chunk is format_chat_stream_chunk
    assert transport_format_chat_stream_done is format_chat_stream_done
    assert transport_format_responses_stream_event is format_responses_stream_event


def test_responses_streaming_public_exports_resolve_to_internal_modules():
    assert (
        ResponsesStreamEventSequencer.__module__
        == "gpt2giga.features.responses._streaming.events"
    )
    assert (
        stream_responses_generator.__module__
        == "gpt2giga.features.responses._streaming.v2"
    )


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_exception_path():
    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(
        req,
        "1",
        chat,
        response_id="1",
        mapper=make_chat_mapper(),
    ):
        lines.append(line)
    assert len(lines) == 2
    assert "Stream interrupted" in lines[0]
    assert lines[1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_stream_responses_generator_exception_path():
    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="1"):
        lines.append(line)
    assert len(lines) == 3
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "event: error" in lines[2]
    assert "Stream interrupted" in lines[2]


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_gigachat_exception():
    mock_logger = MagicMock()
    req = FakeRequest(FakeClientGigaChatError(), logger_=mock_logger)
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(
        req,
        "1",
        chat,
        response_id="1",
        mapper=make_chat_mapper(mock_logger),
    ):
        lines.append(line)
    assert len(lines) == 2
    payload = json.loads(lines[0].removeprefix("data: "))
    assert payload["error"]["type"] == "GigaChatException"
    assert payload["error"]["code"] == "stream_error"
    assert payload["error"]["status_code"] == 403
    assert lines[1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_propagates_cancellation():
    req = FakeRequest(FakeClientCancelled())
    chat = SimpleNamespace(model="giga")
    gen = stream_chat_completion_generator(
        req,
        "1",
        chat,
        response_id="1",
        mapper=make_chat_mapper(),
    )

    with pytest.raises(asyncio.CancelledError):
        await anext(gen)


@pytest.mark.asyncio
async def test_stream_responses_generator_gigachat_exception():
    mock_logger = MagicMock()
    req = FakeRequest(FakeClientGigaChatError(), logger_=mock_logger)
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="1"):
        lines.append(line)
    assert len(lines) == 3
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "event: error" in lines[2]
    assert "stream_error" in lines[2]


@pytest.mark.asyncio
async def test_stream_responses_generator_propagates_cancellation():
    req = FakeRequest(FakeClientCancelled())
    chat = SimpleNamespace(model="giga")
    gen = stream_responses_generator(req, chat, response_id="1")

    first = await anext(gen)
    second = await anext(gen)
    assert "event: response.created" in first
    assert "event: response.in_progress" in second

    with pytest.raises(asyncio.CancelledError):
        await anext(gen)


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_success_with_disconnect():
    class FakeClientWithChunks:
        def astream(self, chat):
            async def gen():
                yield make_chunk(
                    {
                        "choices": [{"delta": {"content": "A"}}],
                        "usage": None,
                        "model": "giga",
                    }
                )
                yield make_chunk(
                    {
                        "choices": [{"delta": {"content": "B"}}],
                        "usage": None,
                        "model": "giga",
                    }
                )

            return gen()

    class DisconnectAfterFirstRequest:
        def __init__(self, client):
            self.app = SimpleNamespace(state=FakeAppState(client, logger_=MagicMock()))
            self._call_count = 0

        async def is_disconnected(self):
            self._call_count += 1
            return self._call_count > 1

    req = DisconnectAfterFirstRequest(FakeClientWithChunks())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(
        req,
        "1",
        chat,
        response_id="1",
        mapper=make_chat_mapper(req.app.state.logger),
    ):
        lines.append(line)
    assert len(lines) == 2
    assert lines[1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_large_chunk_sequence_stays_within_regression_budget():
    class BulkClient:
        def astream(self, chat):
            del chat

            async def gen():
                for index in range(1_500):
                    yield make_chunk(
                        {
                            "choices": [{"delta": {"content": f"chunk-{index}"}}],
                            "usage": None,
                            "model": "giga",
                        }
                    )

            return gen()

    class BulkRequest:
        def __init__(self):
            response_processor = ResponseProcessor(logger=MagicMock())
            self.app = SimpleNamespace(
                state=SimpleNamespace(
                    logger=MagicMock(),
                    providers=RuntimeProviders(
                        gigachat_client=BulkClient(),
                        response_processor=response_processor,
                    ),
                )
            )
            self.state = SimpleNamespace()

        async def is_disconnected(self):
            return False

    req = BulkRequest()
    started_at = time.perf_counter()
    line_count = 0
    last_line = ""
    async for line in stream_chat_completion_generator(
        req,
        "gpt-test",
        {"messages": []},
        response_id="bulk-1",
        giga_client=req.app.state.providers.gigachat_client,
        mapper=GigaChatChatMapper(
            response_processor=req.app.state.providers.response_processor
        ),
    ):
        line_count += 1
        last_line = line
    elapsed = time.perf_counter() - started_at

    assert line_count == 1_501
    assert last_line == format_chat_stream_done()
    assert elapsed < 1.5


@pytest.mark.asyncio
async def test_stream_chat_completion_error_response_format():
    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(
        req,
        "1",
        chat,
        response_id="1",
        mapper=make_chat_mapper(),
    ):
        lines.append(line)

    error_line = lines[0].replace("data: ", "").strip()
    error_data = json.loads(error_line)

    assert "error" in error_data
    assert error_data["error"]["code"] == "internal_error"


@pytest.mark.asyncio
async def test_stream_responses_generator_success():
    req = FakeRequest(FakeResponsesClient())
    chat = SimpleNamespace(model="giga")
    response_store = {}
    lines = []
    async for line in stream_responses_generator(
        req,
        chat,
        response_id="test123",
        response_store=response_store,
    ):
        lines.append(line)

    assert len(lines) == 10

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"
    assert data["response"]["status"] == "in_progress"

    event_type, data = parse_sse(lines[1])
    assert event_type == "response.in_progress"

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["role"] == "assistant"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.content_part.added"
    assert data["part"]["type"] == "output_text"

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "A"

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "B"

    event_type, data = parse_sse(lines[6])
    assert event_type == "response.output_text.done"
    assert data["text"] == "AB"

    event_type, data = parse_sse(lines[7])
    assert event_type == "response.content_part.done"
    assert data["part"]["text"] == "AB"

    event_type, data = parse_sse(lines[8])
    assert event_type == "response.output_item.done"
    assert data["item"]["status"] == "completed"

    event_type, data = parse_sse(lines[9])
    assert event_type == "response.completed"
    assert data["response"]["status"] == "completed"
    assert data["response"]["conversation"] == {"id": "thread-1"}
    assert data["response"]["output"][0]["content"][0]["text"] == "AB"
    assert response_store["resp_test123"]["thread_id"] == "thread-1"


@pytest.mark.asyncio
async def test_stream_responses_generator_legacy_v1_success():
    req = FakeRequest(FakeResponsesClientLegacy())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req,
        chat,
        response_id="legacy123",
        request_data={"model": "gpt-x"},
        api_mode="v1",
    ):
        lines.append(line)

    assert len(lines) == 10

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"
    assert data["response"]["status"] == "in_progress"

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "A"

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "B"

    event_type, data = parse_sse(lines[8])
    assert event_type == "response.output_item.done"
    assert data["item"]["status"] == "completed"

    event_type, data = parse_sse(lines[-1])
    assert event_type == "response.completed"
    assert data["response"]["status"] == "completed"
    assert data["response"].get("conversation") is None
    assert data["response"]["output"][0]["content"][0]["text"] == "AB"


@pytest.mark.asyncio
async def test_stream_responses_generator_preserves_reasoning_config():
    req = FakeRequest(FakeResponsesClient())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req,
        chat,
        response_id="reasoning123",
        request_data={
            "model": "gpt-x",
            "reasoning": {"effort": "high", "summary": "auto"},
        },
    ):
        lines.append(line)

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"
    assert data["response"]["reasoning"] == {"effort": "high", "summary": "auto"}

    event_type, data = parse_sse(lines[-1])
    assert event_type == "response.completed"
    assert data["response"]["reasoning"] == {"effort": "high", "summary": "auto"}


class FakeResponsesClientFunctionCall:
    def astream_v2(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-fc",
                            "role": "assistant",
                            "tools_state_id": "state_123",
                            "content": [
                                {
                                    "function_call": {
                                        "name": "get_weather",
                                        "arguments": {"location": "Moscow"},
                                    }
                                }
                            ],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()


class FakeResponsesClientFunctionCallStreamed:
    def astream_v2(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-fc",
                            "role": "assistant",
                            "tools_state_id": "state_456",
                            "content": [
                                {
                                    "function_call": {
                                        "name": "search",
                                        "arguments": '{"query":',
                                    }
                                }
                            ],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-fc",
                            "role": "assistant",
                            "tools_state_id": "state_456",
                            "content": [
                                {
                                    "function_call": {
                                        "arguments": ' "test"}',
                                    }
                                }
                            ],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()


class FakeResponsesClientReservedWebSearch:
    def astream_v2(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-fc",
                            "role": "assistant",
                            "tools_state_id": "state_999",
                            "content": [
                                {
                                    "function_call": {
                                        "name": "__gpt2giga_user_search_web",
                                        "arguments": {"query": "Moscow"},
                                    }
                                }
                            ],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()


class FakeResponsesClientBuiltinIncomplete:
    def astream_v2(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-2",
                    "messages": [
                        {
                            "message_id": "msg-tool",
                            "role": "assistant",
                            "tools_state_id": "tool-1",
                            "content": [
                                {
                                    "tool_execution": {
                                        "name": "web_search",
                                        "status": "searching",
                                    }
                                }
                            ],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-2",
                    "finish_reason": "length",
                    "usage": {
                        "input_tokens": 8,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 4,
                        "total_tokens": 12,
                    },
                }
            )

        return gen()


class FakeResponsesClientImageGeneration:
    def astream_v2(self, chat):
        async def gen():
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-img",
                    "messages": [
                        {
                            "message_id": "msg-img",
                            "role": "assistant",
                            "tools_state_id": "tool-1",
                            "content": [
                                {
                                    "tool_execution": {
                                        "name": "image_generate",
                                        "status": "generating",
                                    }
                                }
                            ],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-img",
                    "messages": [
                        {
                            "message_id": "msg-img",
                            "role": "assistant",
                            "tools_state_id": "tool-1",
                            "content": [
                                {
                                    "files": [
                                        {
                                            "id": "file-img-1",
                                            "mime": "image/jpeg",
                                            "target": "image",
                                        }
                                    ]
                                }
                            ],
                        }
                    ],
                }
            )
            yield make_chunk(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-img",
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )

        return gen()

    async def aget_file_content(self, file_id):
        return SimpleNamespace(content=f"b64:{file_id}")


@pytest.mark.asyncio
async def test_stream_responses_generator_function_call():
    req = FakeRequest(FakeResponsesClientFunctionCall())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="fc_test"):
        lines.append(line)

    assert len(lines) == 7

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["type"] == "function_call"
    assert data["item"]["name"] == "get_weather"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.function_call_arguments.delta"
    assert "location" in data["delta"]

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.done"
    assert data["name"] == "get_weather"

    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["name"] == "get_weather"


@pytest.mark.asyncio
async def test_stream_responses_generator_function_call_streamed_args():
    req = FakeRequest(FakeResponsesClientFunctionCallStreamed())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="fc_stream"):
        lines.append(line)

    assert len(lines) == 8

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.function_call_arguments.delta"
    assert data["delta"] == '{"query":'

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.delta"
    assert data["delta"] == ' "test"}'

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.function_call_arguments.done"
    assert data["arguments"] == '{"query": "test"}'
    assert data["name"] == "search"

    event_type, data = parse_sse(lines[7])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["arguments"] == '{"query": "test"}'


@pytest.mark.asyncio
async def test_stream_responses_generator_unmaps_reserved_web_search_name():
    req = FakeRequest(FakeResponsesClientReservedWebSearch())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req, chat, response_id="fc_web_search"
    ):
        lines.append(line)

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["name"] == "web_search"

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.done"
    assert data["name"] == "web_search"

    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["name"] == "web_search"


@pytest.mark.asyncio
async def test_stream_responses_generator_emits_builtin_tool_progress_and_incomplete():
    req = FakeRequest(FakeResponsesClientBuiltinIncomplete())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req, chat, response_id="tool_incomplete"
    ):
        lines.append(line)

    assert len(lines) == 6

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["type"] == "web_search_call"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.web_search_call.searching"

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.incomplete"
    assert data["response"]["status"] == "incomplete"
    assert data["response"]["incomplete_details"] == {"reason": "max_output_tokens"}


@pytest.mark.asyncio
async def test_stream_responses_generator_hydrates_image_generation_results():
    req = FakeRequest(FakeResponsesClientImageGeneration())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req, chat, response_id="img_stream_test"
    ):
        lines.append(line)

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"
    assert data["response"]["id"] == "resp_img_stream_test"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.image_generation_call.generating"

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.image_generation_call.completed"

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_item.done"
    assert data["item"]["result"] == "b64:file-img-1"

    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["id"] == "resp_img_stream_test"
    assert data["response"]["output"][0]["result"] == "b64:file-img-1"
