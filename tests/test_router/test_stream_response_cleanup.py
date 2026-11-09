"""Mounted native streaming routes always release pre-acquired model slots."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from gigachat.api.utils import build_headers
from loguru import logger
from starlette.requests import ClientDisconnect

from gpt2giga.app.factory import create_app
from gpt2giga.common.model_concurrency import (
    ModelConcurrencyLimiter,
    ModelConcurrencyTimeoutError,
    model_request_disconnected,
)
from gpt2giga.common.streaming_response import closing_stream
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor


class _StreamingChat:
    def __init__(self, outcome):
        self.outcome = outcome
        self.started = asyncio.Event()
        self.calls = 0
        self.closed = 0
        self.before_close = None
        self.closed_session = None
        self.close_error = False

    async def _chunks(self, mode):
        self.calls += 1
        self.started.set()
        try:
            if self.outcome == "cancel_upstream":
                await asyncio.Event().wait()
            if self.outcome == "error":
                raise RuntimeError("synthetic upstream error")
            if mode == "v1":
                data = {
                    "choices": [
                        {"delta": {"content": "answer"}, "finish_reason": "stop"}
                    ]
                }
            else:
                data = {
                    "messages": [
                        {"role": "assistant", "content": [{"text": "answer"}]}
                    ],
                    "finish_reason": "stop",
                }
            yield SimpleNamespace(model_dump=lambda **_kwargs: data)
        finally:
            if self.before_close is not None:
                await self.before_close()
            await asyncio.sleep(0)
            self.closed_session = build_headers().get("X-Session-ID")
            self.closed += 1
            if self.close_error:
                raise RuntimeError("synthetic upstream close failure")

    def astream(self, _payload):
        return self._chunks("v1")

    def stream(self, _payload):
        return self._chunks("v2")


def _make_app(outcome, *, pass_token=False):
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(mode="DEV", pass_model=True, pass_token=pass_token),
            gigachat={"model": "GigaChat-2-Max"},
        )
    )
    upstream = _StreamingChat(outcome)
    app.state.gigachat_client = SimpleNamespace(
        achat=upstream, astream=upstream.astream
    )
    limiter = ModelConcurrencyLimiter({"GigaChat-2-Max": 1}, acquire_timeout=0)

    async def before_close():
        # Probe capacity as a fresh request; the closing request is disconnected.
        token = model_request_disconnected.set(None)
        try:
            with pytest.raises(ModelConcurrencyTimeoutError):
                async with limiter.limit("GigaChat-2-Max"):
                    pytest.fail("upstream must close before its model slot is released")
        finally:
            model_request_disconnected.reset(token)

    upstream.before_close = before_close
    app.state.model_concurrency_limiter = limiter
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app, upstream, limiter


def _request(mode, protocol):
    path = f"/{mode}/{protocol}"
    payload = {"model": "GigaChat-2-Max", "stream": True}
    if protocol == "responses":
        payload["input"] = "hello"
    else:
        payload["messages"] = [{"role": "user", "content": "hello"}]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-session-id", b"synthetic-stream-session"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    body = json.dumps(payload).encode()

    async def receive():
        nonlocal body
        if body is not None:
            data, body = body, None
            return {"type": "http.request", "body": data, "more_body": False}
        await asyncio.Event().wait()

    return scope, receive


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("protocol", ["chat/completions", "responses"])
@pytest.mark.parametrize(
    "outcome",
    [
        "disconnect_before_body",
        "cancel_before_body",
        "disconnect_during_body",
        "cancel_during_body",
        "cancel_upstream",
        "error",
        "complete",
    ],
)
async def test_stream_releases_slot_on_disconnect_error_or_completion(
    mode, protocol, outcome
):
    app, upstream, limiter = _make_app(outcome)
    scope, receive = _request(mode, protocol)
    messages = []

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.start":
            if outcome == "disconnect_before_body":
                raise OSError("client disconnected before headers")
            if outcome == "cancel_before_body":
                raise asyncio.CancelledError
        if message["type"] == "http.response.body" and upstream.calls:
            if outcome == "disconnect_during_body":
                raise OSError("client disconnected during response body")
            if outcome == "cancel_during_body":
                raise asyncio.CancelledError

    if outcome == "disconnect_before_body":
        with pytest.raises(ClientDisconnect):
            await app(scope, receive, send)
        assert upstream.calls == 0
    elif outcome == "cancel_before_body":
        with pytest.raises(asyncio.CancelledError):
            await app(scope, receive, send)
        assert upstream.calls == 0
    elif outcome == "disconnect_during_body":
        with pytest.raises(ClientDisconnect):
            await app(scope, receive, send)
        assert upstream.closed == 1
    elif outcome == "cancel_during_body":
        with pytest.raises(asyncio.CancelledError):
            await app(scope, receive, send)
        assert upstream.closed == 1
    elif outcome == "cancel_upstream":
        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(upstream.started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert upstream.closed == 1
    else:
        await app(scope, receive, send)
        assert messages[0]["status"] == 200
        assert upstream.closed == 1
        body = b"".join(message.get("body", b"") for message in messages)
        assert (b"internal_error" in body) == (outcome == "error")

    # A new request can enter, but closing both generator and response must not
    # release the same bounded slot twice or increase the configured capacity.
    async with limiter.limit("GigaChat-2-Max"):
        with pytest.raises(ModelConcurrencyTimeoutError):
            async with limiter.limit("GigaChat-2-Max"):
                pytest.fail("one request must still consume the only slot")
    if upstream.calls:
        assert upstream.closed_session == "synthetic-stream-session"


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("protocol", ["chat/completions", "responses"])
async def test_legacy_asgi_disconnect_closes_upstream_inside_cancel_scope(
    mode, protocol
):
    app, upstream, limiter = _make_app("complete")
    scope, receive_body = _request(mode, protocol)
    scope["asgi"]["spec_version"] = "2.0"
    disconnected = asyncio.Event()
    body_received = False

    async def receive():
        nonlocal body_received
        if not body_received:
            body_received = True
            return await receive_body()
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and upstream.calls:
            disconnected.set()
            await asyncio.Event().wait()

    await asyncio.wait_for(app(scope, receive, send), timeout=2)

    assert upstream.closed == 1
    assert upstream.closed_session == "synthetic-stream-session"
    async with limiter.limit("GigaChat-2-Max"):
        with pytest.raises(ModelConcurrencyTimeoutError):
            async with limiter.limit("GigaChat-2-Max"):
                pytest.fail("closing must preserve the configured concurrency limit")


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("protocol", ["chat/completions", "responses"])
async def test_stream_limit_timeout_is_http_429_before_sse_headers(mode, protocol):
    app, upstream, limiter = _make_app("complete")
    scope, receive = _request(mode, protocol)
    messages = []

    async def send(message):
        messages.append(message)

    async with limiter.limit("GigaChat-2-Max"):
        await app(scope, receive, send)

    assert messages[0]["status"] == 429
    assert b"application/json" in dict(messages[0]["headers"])[b"content-type"]
    assert upstream.calls == 0


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("protocol", ["chat/completions", "responses"])
async def test_upstream_close_failure_does_not_mask_client_disconnect(mode, protocol):
    app, upstream, limiter = _make_app("complete")
    upstream.close_error = True
    scope, receive = _request(mode, protocol)

    async def send(message):
        if message["type"] == "http.response.body" and upstream.calls:
            raise OSError("client disconnected while sending")

    with pytest.raises(ClientDisconnect):
        await app(scope, receive, send)

    assert upstream.closed == 1
    async with limiter.limit("GigaChat-2-Max"):
        pass


async def test_stream_close_failure_surfaces_without_an_active_exception():
    async def chunks():
        try:
            yield "first"
        finally:
            raise RuntimeError("synthetic upstream close failure")

    with pytest.raises(RuntimeError, match="synthetic upstream close failure"):
        async with closing_stream(chunks()) as stream:
            assert await anext(stream) == "first"


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize(
    "protocol,normalized",
    [
        ("chat/completions", True),
        ("messages", True),
        ("messages", False),
        ("v1beta/models/GigaChat-2-Max:streamGenerateContent", True),
    ],
)
@pytest.mark.parametrize(
    "failure",
    [
        "headers",
        "body",
        "cancel",
        "complete",
        "asgi2",
        "idle23",
        "idle24",
        "late23",
        "late24",
        "early_close",
        "converter",
    ],
)
async def test_real_sdk_stream_closed_before_model_slot_release(
    mode, protocol, normalized, failure, monkeypatch
):
    import httpx2
    from gigachat import GigaChat

    app, _, limiter = _make_app("complete", pass_token=True)
    app.state.logger = logger
    traffic = SimpleNamespace(emit=AsyncMock())
    metrics = SimpleNamespace(increment=AsyncMock(), observe=AsyncMock())
    app.state.traffic_log_sink = traffic
    app.state.metrics_sink = metrics
    app.state.config.proxy_settings.normalization_mode = "on" if normalized else "off"
    calls = []
    held = []
    outgoing = []
    delegates = []
    from contextlib import asynccontextmanager
    import importlib
    from gpt2giga.providers.gigachat.pool import GigaChatClientPool
    from starlette.requests import Request

    @asynccontextmanager
    async def tracked_closing(stream):
        delegates.append(stream)
        async with closing_stream(stream):
            yield stream

    for module in (
        "providers.gigachat.adapter",
        "protocol.anthropic.streaming",
        "routers.openai.chat_completions",
        "routers.anthropic.messages",
        "routers.gemini.generate_content",
        "sinks.observability.anthropic",
        "common.conversation",
        "common.streaming_response",
    ):
        monkeypatch.setattr(
            importlib.import_module("gpt2giga." + module),
            "closing_stream",
            tracked_closing,
        )
    if failure == "converter":
        target = "gpt2giga.providers.gigachat.streaming"
        original_conversion = importlib.import_module(
            target
        ).GigaChatNormalizedStreamMapper.chunk_to_events

        def fail_conversion(*args, **kwargs):
            original_conversion(*args, **kwargs)
            raise RuntimeError("synthetic stream converter failure")

        monkeypatch.setattr(
            importlib.import_module(target).GigaChatNormalizedStreamMapper,
            "chunk_to_events",
            fail_conversion,
        )

    class TrackedStream(httpx2.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            if mode == "v1":
                chunk = {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": "answer [sources=[",
                            },
                            "finish_reason": None,
                        }
                    ],
                    "created": 1,
                    "model": "GigaChat-2-Max",
                    "object": "chat.completion.chunk",
                }
            else:
                chunk = {
                    "event": "response.message.delta",
                    "model": "GigaChat-2-Max",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [{"text": "answer [sources=["}],
                        }
                    ],
                }
            yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            if failure in {"idle23", "idle24"}:
                await asyncio.Event().wait()
            if mode == "v2":
                yield b'event: response.message.done\ndata: {"event":"response.message.done","model":"GigaChat-2-Max","messages":[],"finish_reason":"stop"}\n\n'
            else:
                yield b"data: [DONE]\n\n"

        async def aclose(self):
            # Inspect slot ownership independently of the disconnected request.
            token = model_request_disconnected.set(None)
            try:
                with pytest.raises(ModelConcurrencyTimeoutError):
                    async with limiter.limit("GigaChat-2-Max"):
                        pytest.fail("slot released before SDK response")
            finally:
                model_request_disconnected.reset(token)
            assert next(iter(pool._entries.values())).active_requests == 1
            self.closed = True

    async def handler(request):
        calls.append(request)
        stream = TrackedStream()
        held.append(stream)
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), trust_env=False
    ) as http:
        owner = GigaChat(
            access_token="synthetic",
            base_url="https://gigachat.test",
            async_http_client=http,
            trust_env=False,
        )
        app.state.gigachat_client = owner
        pool = GigaChatClientPool(
            app.state.config.gigachat_settings, client_factory=lambda *_: owner
        )
        app.state.gigachat_pool = pool
        app.state.config.proxy_settings.pass_token = True
        scope, _ = _request(mode, protocol)
        scope["headers"].append((b"authorization", b"Bearer giga-auth-synthetic"))
        disconnected = asyncio.Event()
        if failure == "asgi2":
            scope["asgi"]["spec_version"] = "2.0"
        elif failure in {"idle23", "late23"}:
            scope["asgi"]["spec_version"] = "2.3"
        if protocol == "messages":
            body = json.dumps(
                {
                    "model": "GigaChat-2-Max",
                    "max_tokens": 20,
                    "stream": True,
                    "messages": [{"role": "user", "content": "hello"}],
                }
            ).encode()
        elif protocol.startswith("v1beta"):
            body = json.dumps(
                {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]}
            ).encode()
        else:
            body = json.dumps(
                {
                    "model": "GigaChat-2-Max",
                    "stream": True,
                    "messages": [{"role": "user", "content": "hello"}],
                }
            ).encode()

        request_body = body
        previous_call_count = 0

        async def receive():
            nonlocal body
            if body is not None:
                data, body = body, None
                return {"type": "http.request", "body": data}
            if failure in {"asgi2", "idle23", "idle24", "late23", "late24"}:
                await disconnected.wait()
                return {"type": "http.disconnect"}
            await asyncio.Event().wait()

        async def send(message):
            outgoing.append(message)
            if (
                failure in {"late23", "late24"}
                and message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                disconnected.set()
                # Ensure the receive owner observes the late disconnect before
                # the response returns to the lifecycle fallback.
                while not model_request_disconnected.get().is_set():
                    await asyncio.sleep(0)
            if failure == "headers" and message["type"] == "http.response.start":
                raise OSError("synthetic headers disconnect")
            if (
                len(calls) > previous_call_count
                and message["type"] == "http.response.body"
            ):
                if failure in {"asgi2", "idle23", "idle24"}:
                    disconnected.set()
                    await asyncio.sleep(0)
                if failure == "body":
                    raise OSError("synthetic body disconnect")
                if failure == "cancel":
                    raise asyncio.CancelledError

        if failure == "early_close":
            scope["app"] = app
            scope["state"] = {"gigachat_client": owner}
            request = Request(scope, receive)
            async with pool.acquire("giga-auth-synthetic"):
                if protocol == "messages":
                    endpoint = importlib.import_module(
                        "gpt2giga.routers.anthropic.messages"
                    ).messages
                    response = await endpoint(request)
                elif protocol.startswith("v1beta"):
                    endpoint = importlib.import_module(
                        "gpt2giga.routers.gemini.generate_content"
                    ).stream_generate_content
                    response = await endpoint("GigaChat-2-Max", request)
                else:
                    endpoint = importlib.import_module(
                        "gpt2giga.routers.openai.chat_completions"
                    ).chat_completions
                    response = await endpoint(request)
                outer = response.body_iterator
                delegates.append(outer)
                while not calls:
                    await anext(outer)
                await outer.aclose()
        elif failure in {
            "complete",
            "asgi2",
            "idle23",
            "idle24",
            "late23",
            "late24",
            "converter",
        }:
            await asyncio.wait_for(app(scope, receive, send), timeout=2)
        else:
            with pytest.raises(
                asyncio.CancelledError if failure == "cancel" else ClientDisconnect
            ):
                await app(scope, receive, send)
        if failure in {"idle23", "idle24"}:
            # Reuse the same application/provider for a series, so assertions
            # cover steady state rather than cleanup of a disposable fixture.
            for _ in range(4):
                assert app.state.response_processor._stream_reasoning_parsers == {}
                assert app.state.response_processor._stream_source_renderers == {}
                assert app.state.bridge_request_lifecycle.active_requests == 0
                assert next(iter(pool._entries.values())).active_requests == 0
                disconnected.clear()
                previous_call_count = len(calls)
                body = request_body
                await asyncio.wait_for(app(scope, receive, send), timeout=2)
        expected_calls = 5 if failure in {"idle23", "idle24"} else 1
        assert len(calls) == (0 if failure == "headers" else expected_calls)
        assert all(stream.closed for stream in held)
        assert app.state.bridge_request_lifecycle.active_requests == 0
        assert app.state.response_processor._stream_reasoning_parsers == {}
        assert app.state.response_processor._stream_source_renderers == {}
        wire = b"".join(message.get("body", b"") for message in outgoing)
        if failure == "converter":
            assert b"error" in wire
        elif failure in {"complete", "late23", "late24"}:
            assert b"answer" in wire
            assert b'"error"' not in wire
        if failure in {"idle23", "idle24", "complete", "late23", "late24"}:
            aborted = failure in {"idle23", "idle24"}
            events = [
                call.args[0]
                for call in traffic.emit.call_args_list
                if call.args[0].metadata.get("lifecycle", "").startswith("streaming_")
            ]
            assert len(events) == expected_calls
            for event in events:
                assert event.metadata["lifecycle"] == (
                    "streaming_aborted" if aborted else "streaming_completed"
                )
                assert event.status_code == (499 if aborted else 200)
                assert event.error_type == ("stream_cancelled" if aborted else None)
                assert "giga-auth-synthetic" not in repr(event)
            disconnects = [
                call
                for call in metrics.increment.call_args_list
                if call.args[0] == "gpt2giga_stream_disconnects_total"
            ]
            assert len(disconnects) == (expected_calls if aborted else 0)
            assert all(call.args[1] == 1 for call in disconnects)
            assert all(
                message["status"] == 200
                for message in outgoing
                if message["type"] == "http.response.start"
            )
            if protocol == "chat/completions":
                assert (b"[DONE]" in wire) is not aborted
            assert not any(
                "watch_disconnect" in getattr(task.get_coro(), "__qualname__", "")
                for task in asyncio.all_tasks()
                if not task.done()
            )
        async with limiter.limit("GigaChat-2-Max"):
            pass
        assert next(iter(pool._entries.values())).active_requests == 0
        assert not http.is_closed
        assert delegates or failure == "headers"
        assert all(getattr(stream, "ag_frame", None) is None for stream in delegates)
        await pool.aclose()
