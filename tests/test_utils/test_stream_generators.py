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
    assert len(lines) == 2
    assert "Stream interrupted" in lines[0]
    assert lines[1].strip() == "data: [DONE]"


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
    assert len(lines) == 2
    assert "GigaChatException" in lines[0]
    assert "stream_error" in lines[0]
    assert lines[1].strip() == "data: [DONE]"


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
