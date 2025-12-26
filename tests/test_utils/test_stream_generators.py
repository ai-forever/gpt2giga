from types import SimpleNamespace

import pytest

from gpt2giga.utils import (
    stream_chat_completion_generator,
    stream_responses_generator,
)


class FakeResponseProcessor:
    def process_stream_chunk(self, chunk, model):
        return {"model": model, "delta": chunk.model_dump()["choices"][0]["delta"]}

    def process_stream_chunk_response(
        self, chunk, sequence_number: int, response_id: str
    ):
        return {
            "id": response_id,
            "sequence": sequence_number,
            "delta": chunk.model_dump()["choices"][0]["delta"],
        }


class FakeClient:
    async def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                dict=lambda: {
                    "choices": [{"delta": {"content": "A"}}],
                    "usage": None,
                    "model": "giga",
                }
            )
            yield SimpleNamespace(
                dict=lambda: {
                    "choices": [{"delta": {"content": "B"}}],
                    "usage": None,
                    "model": "giga",
                }
            )

        return gen()


class FakeClientError:
    async def astream(self, chat):
        async def gen():
            raise RuntimeError("boom")

        return gen()


class FakeAppState:
    def __init__(self, client):
        self.gigachat_client = client
        self.response_processor = FakeResponseProcessor()
        self.rquid = "rquid-1"


class FakeRequest:
    def __init__(self, client, disconnected: bool = False):
        self.app = SimpleNamespace(state=FakeAppState(client))
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
