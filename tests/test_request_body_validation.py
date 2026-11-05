"""Request body limits apply to received bytes before parsing or upstream I/O."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from gpt2giga.app.factory import create_app
from gpt2giga.middlewares.request_validation import RequestValidationMiddleware
from gpt2giga.models.config import ProxyConfig, ProxySettings


def _app(*, limit: int = 1024):
    app = create_app(ProxyConfig(proxy=ProxySettings(max_request_body_bytes=limit)))
    upstream = AsyncMock(return_value={"data": [{"embedding": [0.5], "index": 0}]})
    app.state.gigachat_client = SimpleNamespace(aembeddings=upstream)
    return app, upstream


def test_mounted_embeddings_rejects_oversized_chunked_body_before_upstream():
    app, upstream = _app(limit=16)
    response = TestClient(app).post(
        "/v1/embeddings",
        content=iter([b'{"input":"', b"a" * 32, b'"}']),
        headers={"content-type": "application/json"},
    )

    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_entity_too_large"
    upstream.assert_not_awaited()


@pytest.mark.parametrize("content_length", [None, b"1", b"invalid"])
async def test_body_limit_counts_all_chunks_and_stops_reading_at_limit(content_length):
    messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": True},
        ]
    )
    receive = AsyncMock(side_effect=lambda: next(messages))
    send = AsyncMock()
    downstream = AsyncMock()
    headers = [] if content_length is None else [(b"content-length", content_length)]

    await RequestValidationMiddleware(downstream, max_body_bytes=5)(
        {"type": "http", "method": "POST", "headers": headers}, receive, send
    )

    downstream.assert_not_awaited()
    assert receive.await_count == 2
    assert send.await_args_list[0].args[0]["status"] == 413


async def test_body_at_limit_reaches_downstream_and_disconnect_is_preserved():
    messages = iter(
        [
            {"type": "http.request", "body": b"", "more_body": True},
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"45", "more_body": False},
            {"type": "http.disconnect"},
        ]
    )
    received = []

    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            received.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        assert await receive() == {"type": "http.disconnect"}

    await RequestValidationMiddleware(downstream, max_body_bytes=5)(
        {"type": "http", "method": "POST", "headers": []},
        AsyncMock(side_effect=lambda: next(messages)),
        AsyncMock(),
    )

    assert b"".join(received) == b"12345"


async def test_body_disconnect_during_upload_does_not_enter_downstream():
    messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    downstream = AsyncMock()
    send = AsyncMock()

    await RequestValidationMiddleware(downstream, max_body_bytes=5)(
        {"type": "http", "method": "POST", "headers": []},
        AsyncMock(side_effect=lambda: next(messages)),
        send,
    )

    downstream.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.parametrize("body", [b'{"input":"\xff"}', b"\xff\xfe{"])
def test_invalid_json_encoding_returns_client_error_without_upstream(body):
    app, upstream = _app()

    response = TestClient(app).post(
        "/v1/embeddings", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "invalid_json"
    upstream.assert_not_awaited()
