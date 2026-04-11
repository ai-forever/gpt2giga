from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import gigachat.exceptions
import pytest

from gpt2giga.providers.gigachat.streaming import (
    GigaChatStreamError,
    iter_chat_stream_chunks,
    iter_stream_with_disconnect,
    report_stream_failure,
)


class DummyRequest:
    def __init__(self, disconnected: list[bool]) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace())
        self.state = SimpleNamespace()
        self._disconnected = disconnected
        self._index = 0

    async def is_disconnected(self) -> bool:
        if self._index >= len(self._disconnected):
            return self._disconnected[-1]
        value = self._disconnected[self._index]
        self._index += 1
        return value


@pytest.mark.asyncio
async def test_iter_stream_with_disconnect_stops_after_disconnect():
    request = DummyRequest([False, True])
    logger = MagicMock()

    async def stream():
        yield "chunk-1"
        yield "chunk-2"

    chunks = []
    async for chunk in iter_stream_with_disconnect(
        request,
        stream(),
        logger=logger,
        rquid="rq-1",
    ):
        chunks.append(chunk)

    assert chunks == ["chunk-1"]
    logger.info.assert_called_once_with("[rq-1] Client disconnected during streaming")


def test_report_stream_failure_wraps_provider_error():
    request = DummyRequest([False])
    logger = MagicMock()

    failure = report_stream_failure(
        request,
        gigachat.exceptions.GigaChatException("provider boom"),
        logger=logger,
        rquid="rq-2",
    )

    assert failure.error_type == "GigaChatException"
    assert failure.message == "provider boom"
    assert failure.code == "stream_error"
    assert request.state._request_audit_context["error_type"] == "GigaChatException"
    logger.error.assert_called_once()


def test_report_stream_failure_normalizes_unexpected_error():
    request = DummyRequest([False])
    logger = MagicMock()

    failure = report_stream_failure(
        request,
        RuntimeError("boom"),
        logger=logger,
        rquid="rq-3",
    )

    assert failure.error_type == "RuntimeError"
    assert failure.message == "Stream interrupted"
    assert failure.code == "internal_error"
    assert request.state._request_audit_context["error_type"] == "RuntimeError"
    logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_iter_chat_stream_chunks_wraps_gigachat_exception():
    class FailingClient:
        def astream(self, _chat):
            async def gen():
                raise gigachat.exceptions.GigaChatException("upstream failed")
                yield  # pragma: no cover

            return gen()

    with pytest.raises(GigaChatStreamError) as exc_info:
        async for _ in iter_chat_stream_chunks(FailingClient(), {"messages": []}):
            pass

    assert exc_info.value.error_type == "GigaChatException"
    assert exc_info.value.message == "upstream failed"
