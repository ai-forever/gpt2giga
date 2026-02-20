import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import gigachat.exceptions
import pytest

from gpt2giga.common.streaming import (
    stream_chat_completion_generator,
    stream_responses_generator,
)


class FakeResponseProcessor:
    def process_stream_chunk(self, chunk, model, response_id: str):
        return {
            "id": response_id,
            "model": model,
            "delta": chunk.model_dump()["choices"][0]["delta"],
        }

    def process_stream_chunk_response(
        self, chunk, sequence_number: int, response_id: str
    ):
        return {
            "id": response_id,
            "sequence": sequence_number,
            "delta": chunk.model_dump()["choices"][0]["delta"],
        }


class FakeClient:
    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [{"delta": {"content": "A"}}],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [{"delta": {"content": "B"}}],
                    "usage": None,
                    "model": "giga",
                }
            )

        return gen()


class FakeClientError:
    def astream(self, chat):
        async def gen():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        return gen()


class FakeClientGigaChatError:
    """Client that raises GigaChatException"""

    def astream(self, chat):
        async def gen():
            # Используем базовый GigaChatException который не требует дополнительных аргументов
            raise gigachat.exceptions.GigaChatException("GigaChat API error occurred")
            yield  # pragma: no cover

        return gen()


class FakeClientCancelled:
    def astream(self, chat):
        async def gen():
            raise asyncio.CancelledError()
            yield  # pragma: no cover

        return gen()


class FakeAppState:
    def __init__(self, client, logger=None):
        self.gigachat_client = client
        self.response_processor = FakeResponseProcessor()
        self.rquid = "rquid-1"
        self.logger = logger


class FakeRequest:
    def __init__(self, client, disconnected: bool = False, logger=None):
        self.app = SimpleNamespace(state=FakeAppState(client, logger))
        self._disconnected = disconnected

    async def is_disconnected(self):
        return self._disconnected


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_exception_path():
    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(req, "1", chat, response_id="1"):
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
    # Now we expect: response.created, response.in_progress, then error
    # (output_item.added and content_part.added are emitted lazily on first content)
    assert len(lines) == 3
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "Stream interrupted" in lines[2]
    assert "event: error" in lines[2]


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_gigachat_exception():
    """Тест обработки GigaChatException с правильным типом ошибки"""
    logger = MagicMock()
    req = FakeRequest(FakeClientGigaChatError(), logger=logger)
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(req, "1", chat, response_id="1"):
        lines.append(line)
    assert len(lines) == 2
    # Проверяем, что ошибка содержит тип и код
    assert "GigaChatException" in lines[0]
    assert "stream_error" in lines[0]
    assert lines[1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_stream_chat_completion_generator_propagates_cancellation():
    req = FakeRequest(FakeClientCancelled())
    chat = SimpleNamespace(model="giga")
    gen = stream_chat_completion_generator(req, "1", chat, response_id="1")

    with pytest.raises(asyncio.CancelledError):
        await anext(gen)


@pytest.mark.asyncio
async def test_stream_responses_generator_gigachat_exception():
    """Тест обработки GigaChatException в responses generator"""
    logger = MagicMock()
    req = FakeRequest(FakeClientGigaChatError(), logger=logger)
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="1"):
        lines.append(line)
    # Now we expect: response.created, response.in_progress, then error
    # (output_item.added and content_part.added are emitted lazily on first content)
    assert len(lines) == 3
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "GigaChat" in lines[2]
    assert "stream_error" in lines[2]
    assert "event: error" in lines[2]


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
    """Тест корректного завершения при отключении клиента"""

    class FakeClientWithChunks:
        def astream(self, chat):
            async def gen():
                yield SimpleNamespace(
                    model_dump=lambda: {
                        "choices": [{"delta": {"content": "A"}}],
                        "usage": None,
                        "model": "giga",
                    }
                )
                yield SimpleNamespace(
                    model_dump=lambda: {
                        "choices": [{"delta": {"content": "B"}}],
                        "usage": None,
                        "model": "giga",
                    }
                )

            return gen()

    # Клиент отключается после первого чанка
    class DisconnectAfterFirstRequest:
        def __init__(self, client):
            self.app = SimpleNamespace(state=FakeAppState(client, logger=MagicMock()))
            self._call_count = 0

        async def is_disconnected(self):
            self._call_count += 1
            return self._call_count > 1  # Disconnect after first call

    req = DisconnectAfterFirstRequest(FakeClientWithChunks())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(req, "1", chat, response_id="1"):
        lines.append(line)
    # Должен быть только 1 чанк данных + DONE
    assert len(lines) == 2
    assert lines[1].strip() == "data: [DONE]"


@pytest.mark.asyncio
async def test_stream_chat_completion_error_response_format():
    """Тест формата ответа об ошибке в стриминге"""
    import json

    req = FakeRequest(FakeClientError())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_chat_completion_generator(req, "1", chat, response_id="1"):
        lines.append(line)

    # Парсим ошибку
    error_line = lines[0].replace("data: ", "").strip()
    error_data = json.loads(error_line)

    assert "error" in error_data
    assert "message" in error_data["error"]
    assert "type" in error_data["error"]
    assert "code" in error_data["error"]
    assert error_data["error"]["code"] == "internal_error"


@pytest.mark.asyncio
async def test_stream_responses_generator_success():
    """Test successful streaming with all proper SSE events"""
    import json

    req = FakeRequest(FakeClient())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="test123"):
        lines.append(line)

    # Expected events:
    # 1. response.created
    # 2. response.in_progress
    # 3. response.output_item.added
    # 4. response.content_part.added
    # 5. response.output_text.delta (for "A")
    # 6. response.output_text.delta (for "B")
    # 7. response.output_text.done
    # 8. response.content_part.done
    # 9. response.output_item.done
    # 10. response.completed
    assert len(lines) == 10

    # Parse and verify each event
    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"
    assert data["type"] == "response.created"
    assert data["response"]["status"] == "in_progress"

    event_type, data = parse_sse(lines[1])
    assert event_type == "response.in_progress"
    assert data["type"] == "response.in_progress"

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["type"] == "response.output_item.added"
    assert data["item"]["role"] == "assistant"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.content_part.added"
    assert data["type"] == "response.content_part.added"
    assert data["part"]["type"] == "output_text"

    # Delta events for "A" and "B"
    event_type, data = parse_sse(lines[4])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "A"

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_text.delta"
    assert data["delta"] == "B"

    # Finalization events
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
    assert data["response"]["output"][0]["content"][0]["text"] == "AB"


class FakeClientFunctionCall:
    """Client that returns function call chunks"""

    def astream(self, chat):
        async def gen():
            # First chunk with function name
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "function_call": {
                                    "name": "get_weather",
                                    "arguments": {"location": "Moscow"},
                                },
                                "functions_state_id": "state_123",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            # Second chunk with finish_reason
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "function_call",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": "giga",
                }
            )

        return gen()


class FakeClientFunctionCallStreamed:
    """Client that returns function call with arguments streamed across multiple chunks"""

    def astream(self, chat):
        async def gen():
            # First chunk with function name
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "function_call": {
                                    "name": "search",
                                    "arguments": '{"query":',
                                },
                                "functions_state_id": "state_456",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            # Second chunk with more arguments
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "function_call": {
                                    "arguments": ' "test"}',
                                },
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            # Final chunk
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "function_call",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": "giga",
                }
            )

        return gen()


class FakeClientFunctionCallReservedWebSearch:
    """Client that returns a reserved tool name (aliased on GigaChat side)."""

    def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "function_call": {
                                    "name": "__gpt2giga_user_search_web",
                                    "arguments": {"query": "Moscow"},
                                },
                                "functions_state_id": "state_999",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield SimpleNamespace(
                model_dump=lambda: {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "function_call",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "model": "giga",
                }
            )

        return gen()


@pytest.mark.asyncio
async def test_stream_responses_generator_function_call():
    """Test streaming with function call (single chunk)"""
    import json

    req = FakeRequest(FakeClientFunctionCall())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="fc_test"):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    # Expected events:
    # 1. response.created
    # 2. response.in_progress
    # 3. response.output_item.added (function_call)
    # 4. response.function_call_arguments.delta
    # 5. response.function_call_arguments.done
    # 6. response.output_item.done
    # 7. response.completed
    assert len(lines) == 7

    event_type, data = parse_sse(lines[0])
    assert event_type == "response.created"

    event_type, data = parse_sse(lines[1])
    assert event_type == "response.in_progress"

    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["type"] == "function_call"
    assert data["item"]["name"] == "get_weather"
    assert data["item"]["status"] == "in_progress"

    event_type, data = parse_sse(lines[3])
    assert event_type == "response.function_call_arguments.delta"
    assert "location" in data["delta"]

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.done"
    assert data["name"] == "get_weather"
    assert "location" in data["arguments"]

    event_type, data = parse_sse(lines[5])
    assert event_type == "response.output_item.done"
    assert data["item"]["type"] == "function_call"
    assert data["item"]["status"] == "completed"
    assert data["item"]["name"] == "get_weather"

    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["status"] == "completed"
    assert data["response"]["output"][0]["type"] == "function_call"
    assert data["response"]["output"][0]["name"] == "get_weather"


@pytest.mark.asyncio
async def test_stream_responses_generator_function_call_streamed_args():
    """Test streaming with function call arguments split across multiple chunks"""
    import json

    req = FakeRequest(FakeClientFunctionCallStreamed())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="fc_stream"):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    # Expected events:
    # 1. response.created
    # 2. response.in_progress
    # 3. response.output_item.added (function_call)
    # 4. response.function_call_arguments.delta (first part)
    # 5. response.function_call_arguments.delta (second part)
    # 6. response.function_call_arguments.done
    # 7. response.output_item.done
    # 8. response.completed
    assert len(lines) == 8

    # Verify delta events
    event_type, data = parse_sse(lines[3])
    assert event_type == "response.function_call_arguments.delta"
    assert data["delta"] == '{"query":'

    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.delta"
    assert data["delta"] == ' "test"}'

    # Verify final arguments are concatenated
    event_type, data = parse_sse(lines[5])
    assert event_type == "response.function_call_arguments.done"
    assert data["arguments"] == '{"query": "test"}'
    assert data["name"] == "search"

    # Verify completed output
    event_type, data = parse_sse(lines[7])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["type"] == "function_call"
    assert data["response"]["output"][0]["name"] == "search"
    assert data["response"]["output"][0]["arguments"] == '{"query": "test"}'


@pytest.mark.asyncio
async def test_stream_responses_generator_unmaps_reserved_web_search_name():
    """Reserved tool name coming from GigaChat must be mapped back for client."""
    import json

    req = FakeRequest(FakeClientFunctionCallReservedWebSearch())
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(
        req, chat, response_id="fc_web_search"
    ):
        lines.append(line)

    def parse_sse(line):
        parts = line.strip().split("\n")
        event_type = parts[0].replace("event: ", "")
        data = json.loads(parts[1].replace("data: ", ""))
        return event_type, data

    # response.output_item.added contains the name
    event_type, data = parse_sse(lines[2])
    assert event_type == "response.output_item.added"
    assert data["item"]["name"] == "web_search"

    # done event must also contain unmapped name
    event_type, data = parse_sse(lines[4])
    assert event_type == "response.function_call_arguments.done"
    assert data["name"] == "web_search"

    # final output must contain unmapped name
    event_type, data = parse_sse(lines[6])
    assert event_type == "response.completed"
    assert data["response"]["output"][0]["name"] == "web_search"
