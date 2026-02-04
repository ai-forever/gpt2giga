from types import SimpleNamespace
from unittest.mock import MagicMock

import gigachat.exceptions
import pytest

from gpt2giga.utils import (
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
    # Now we expect: response.created, response.in_progress, output_item.added, content_part.added, then error
    assert len(lines) == 5
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "event: response.output_item.added" in lines[2]
    assert "event: response.content_part.added" in lines[3]
    assert "Stream interrupted" in lines[4]
    assert "event: error" in lines[4]


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
async def test_stream_responses_generator_gigachat_exception():
    """Тест обработки GigaChatException в responses generator"""
    logger = MagicMock()
    req = FakeRequest(FakeClientGigaChatError(), logger=logger)
    chat = SimpleNamespace(model="giga")
    lines = []
    async for line in stream_responses_generator(req, chat, response_id="1"):
        lines.append(line)
    # Now we expect: response.created, response.in_progress, output_item.added, content_part.added, then error
    assert len(lines) == 5
    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "event: response.output_item.added" in lines[2]
    assert "event: response.content_part.added" in lines[3]
    assert "GigaChat" in lines[4]
    assert "stream_error" in lines[4]
    assert "event: error" in lines[4]


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
