import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi import Request
import pytest
from starlette.testclient import TestClient

from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.context import RequestContext
from gpt2giga.core.context import get_request_context
from gpt2giga.models.config import ProxyConfig
from gpt2giga.models.config import ProxySettings
from gpt2giga.middlewares.rquid_context import RquidMiddleware
from gpt2giga.middlewares.pass_token import PassTokenMiddleware
from gpt2giga.middlewares.path_normalizer import PathNormalizationMiddleware
from gpt2giga.middlewares.request_validation import RequestValidationMiddleware
from gpt2giga.sinks.logs.emission import wrap_traffic_log_body_iterator

app = FastAPI()
app.add_middleware(PathNormalizationMiddleware, valid_roots=["v1"])


@app.get("/v1/test")
def v1_test():
    return {"ok": True}


def test_path_norm_redirect():
    client = TestClient(app)
    resp = client.get("/abc/v1/test")
    # Раньше тут был HTTP redirect (307), теперь путь переписывается без редиректа,
    # чтобы не терять body у POST запросов.
    assert resp.status_code == 200
    assert resp.history == []


def test_path_norm_preserves_query_params():
    client = TestClient(app)
    resp = client.get("/zzz/v1/test?x=1&y=2")
    assert resp.status_code == 200
    # Убедимся, что конечная ручка получила запрос (просто факт 200 для тестовой ручки)


def test_path_norm_no_redirect_when_already_normalized():
    client = TestClient(app)
    resp = client.get("/v1/test")
    assert resp.status_code == 200


def test_path_norm_no_redirect_for_unknown_root():
    client = TestClient(app)
    # Нет известного корня -> остаётся 404
    resp = client.get("/abc/zzz/test")
    assert resp.status_code == 404


def test_path_norm_keeps_messages_batches_prefix():
    test_app = FastAPI()
    test_app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=["v1", "messages", "batches"],
    )

    @test_app.post("/v1/messages/batches")
    def create_batch():
        return {"ok": True}

    client = TestClient(test_app)
    resp = client.post("/proxy/v1/messages/batches", json={"requests": []})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_path_norm_collapses_duplicate_v1_prefix():
    test_app = FastAPI()
    test_app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=["v1", "messages"],
    )

    @test_app.post("/v1/messages")
    def create_message():
        return {"ok": True}

    client = TestClient(test_app)

    assert client.post("/v1/v1/messages", json={}).status_code == 200
    assert client.post("/proxy/v1/v1/messages", json={}).status_code == 200


def test_path_norm_collapses_duplicate_v2_prefix():
    test_app = FastAPI()
    test_app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=["v2", "chat"],
    )

    @test_app.post("/v2/chat/completions")
    def create_chat_completion():
        return {"ok": True}

    client = TestClient(test_app)

    assert client.post("/v2/v2/chat/completions", json={}).status_code == 200
    assert client.post("/proxy/v2/v2/chat/completions", json={}).status_code == 200


def test_pass_token_middleware(monkeypatch):
    test_app = FastAPI()
    test_app.add_middleware(PassTokenMiddleware)

    class FakeGigaChat:
        def __init__(self, **kwargs):
            self._settings = SimpleNamespace(**kwargs)

    # Mock settings
    config = SimpleNamespace(
        proxy_settings=SimpleNamespace(pass_token=True),
        gigachat_settings=SimpleNamespace(model_dump=lambda: {}),
    )
    test_app.state.config = config

    # Ensure middleware stays offline by stubbing GigaChat construction in gigachat module
    monkeypatch.setattr("gigachat.GigaChat", FakeGigaChat)

    # Base (app-scoped) GigaChat client
    test_app.state.gigachat_client = FakeGigaChat()

    # No connection pool for this test (legacy behavior fallback)
    test_app.state.gigachat_pool = None

    # Mock logger
    test_app.state.logger = MagicMock()

    @test_app.get("/check")
    def check_token(request: Request):
        client = request.state.gigachat_client
        access_token = getattr(getattr(client, "_settings", None), "access_token", None)
        return {"ok": True, "access_token": access_token}

    client = TestClient(test_app)

    # Test valid token
    resp = client.get("/check", headers={"Authorization": "Bearer giga-auth-mytoken"})
    assert resp.status_code == 200
    # pass_token_to_gigachat logic should put 'mytoken' into access_token on request-scoped client
    assert resp.json()["access_token"] == "mytoken"

    # Test error handling
    # Mock create_gigachat_client_for_request to raise exception
    def broken_create(*args, **kwargs):
        raise ValueError("Boom")

    monkeypatch.setattr(
        "gpt2giga.middlewares.pass_token.create_gigachat_client_for_request",
        broken_create,
    )

    resp = client.get("/check", headers={"Authorization": "Bearer giga-auth-fail"})
    assert resp.status_code == 200
    assert resp.json()["access_token"] is None
    test_app.state.logger.warning.assert_called()

    # Test pass_token disabled
    config.proxy_settings.pass_token = False
    test_app.state.logger.warning.reset_mock()
    resp = client.get("/check", headers={"Authorization": "Bearer giga-auth-ignored"})
    assert resp.status_code == 200
    # Nothing should happen, no warning
    test_app.state.logger.warning.assert_not_called()


def test_rquid_middleware_sets_request_context_and_header():
    test_app = FastAPI()
    test_app.add_middleware(RquidMiddleware)

    @test_app.get("/v1/messages")
    async def context_view(request: Request):
        context = get_request_context()
        assert context is request.state.request_context
        return {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "protocol": context.protocol,
            "route": context.route,
            "method": context.method,
            "caller_name": context.caller_name,
            "caller_category": context.caller_category,
            "caller_sdk": context.caller_sdk,
            "caller_client_family": context.caller_client_family,
            "annotations": context.annotations,
            "client_ip_hash": context.client_ip_hash,
            "api_key_hash": context.api_key_hash,
        }

    client = TestClient(test_app)
    response = client.get(
        "/v1/messages",
        headers={
            "Authorization": "Bearer local-secret",
            "x-trace-id": "trace-123",
            "user-agent": "OpenAI/Python 1.2.3",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert response.headers["x-request-id"] == data["request_id"]
    assert data["trace_id"] == "trace-123"
    assert data["protocol"] == "anthropic"
    assert data["route"] == "/v1/messages"
    assert data["method"] == "GET"
    assert data["caller_name"] == "openai-python"
    assert data["caller_category"] == "sdk"
    assert data["caller_sdk"] == "openai-python"
    assert data["caller_client_family"] == "openai"
    assert data["annotations"]["caller"]["sdk"] == "openai-python"
    assert data["client_ip_hash"].startswith("pbkdf2-sha256:")
    assert data["api_key_hash"].startswith("pbkdf2-sha256:")
    assert "local-secret" not in data["api_key_hash"]


def test_rquid_middleware_infers_v2_protocols():
    test_app = FastAPI()
    test_app.add_middleware(RquidMiddleware)

    @test_app.get("/v2/messages")
    async def anthropic_context():
        return {"protocol": get_request_context().protocol}

    @test_app.get("/v2/model/info")
    async def litellm_context():
        return {"protocol": get_request_context().protocol}

    client = TestClient(test_app)

    assert client.get("/v2/messages").json()["protocol"] == "anthropic"
    assert client.get("/v2/model/info").json()["protocol"] == "litellm"


def test_read_request_json_updates_request_context_model():
    test_app = FastAPI()
    test_app.add_middleware(RquidMiddleware)

    @test_app.post("/chat/completions")
    async def read_body(request: Request):
        await read_request_json(request)
        context = get_request_context()
        return {"model_requested": context.model_requested}

    client = TestClient(test_app)
    response = client.post(
        "/chat/completions",
        json={"model": "GigaChat-2-Max", "messages": []},
    )

    assert response.status_code == 200
    assert response.json() == {"model_requested": "GigaChat-2-Max"}


class RecordingTrafficSink:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)

    async def flush(self):
        return None


class RecordingObservabilitySink:
    def __init__(self):
        self.events = []

    async def emit(self, name, attributes=None, *, context=None):
        self.events.append(
            {
                "name": name,
                "attributes": attributes or {},
                "context": context,
            }
        )

    async def flush(self):
        return None


class RecordingMetricsSink:
    def __init__(self):
        self.counters = []
        self.observations = []

    async def increment(self, name, value=1, attributes=None):
        self.counters.append((name, value, attributes or {}))

    async def observe(self, name, value, attributes=None):
        self.observations.append((name, value, attributes or {}))

    async def flush(self):
        return None


def test_rquid_middleware_emits_traffic_event_for_completed_request():
    test_app = FastAPI()
    sink = RecordingTrafficSink()
    test_app.state.traffic_log_sink = sink
    test_app.add_middleware(RquidMiddleware)

    @test_app.get("/v1/models")
    async def models():
        return {"data": []}

    client = TestClient(test_app)
    response = client.get(
        "/v1/models",
        headers={"Authorization": "Bearer local-secret", "x-trace-id": "trace-1"},
    )

    assert response.status_code == 200
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.request_id == response.headers["x-request-id"]
    assert event.trace_id == "trace-1"
    assert event.protocol == "openai"
    assert event.route == "/v1/models"
    assert event.method == "GET"
    assert event.status_code == 200
    assert event.provider == "gigachat"
    assert event.api_key_hash.startswith("pbkdf2-sha256:")
    assert event.metadata["lifecycle"] == "request_completed"
    assert event.latency_ms >= 0


def test_rquid_middleware_captures_redacted_traffic_payloads_when_enabled():
    test_app = FastAPI()
    sink = RecordingTrafficSink()
    test_app.state.traffic_log_sink = sink
    test_app.state.config = ProxyConfig(
        proxy=ProxySettings(
            traffic_log_capture_content=True,
            traffic_log_redact_extra_keys=["custom_secret", "x-custom-secret"],
        )
    )
    test_app.add_middleware(RquidMiddleware)

    @test_app.post("/chat/completions")
    async def chat(request: Request):
        data = await read_request_json(request)
        return {
            "ok": True,
            "content": data["messages"][0]["content"],
            "token": "response-secret",
        }

    client = TestClient(test_app)
    response = client.post(
        "/chat/completions",
        headers={
            "Authorization": "Bearer local-secret",
            "x-custom-secret": "header-secret",
        },
        json={
            "model": "GigaChat",
            "api_key": "body-secret",
            "custom_secret": "body-custom-secret",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.request_headers_redacted["authorization"] == "***"
    assert event.request_headers_redacted["x-custom-secret"] == "***"
    assert event.request_body_redacted["api_key"] == "***"
    assert event.request_body_redacted["custom_secret"] == "***"
    assert event.request_body_redacted["messages"][0]["content"] == "hello"
    assert event.response_body_redacted == {
        "ok": True,
        "content": "hello",
        "token": "***",
    }


def test_rquid_middleware_emits_observability_event_for_completed_request():
    test_app = FastAPI()
    sink = RecordingObservabilitySink()
    test_app.state.observability_sink = sink
    test_app.add_middleware(RquidMiddleware)

    @test_app.get("/v1/models")
    async def models():
        return {"data": []}

    client = TestClient(test_app)
    response = client.get(
        "/v1/models",
        headers={"x-trace-id": "trace-1", "user-agent": "claude-code/1.0"},
    )

    assert response.status_code == 200
    assert [event["name"] for event in sink.events] == ["gpt2giga.request"]
    event = sink.events[0]
    assert event["context"].trace_id == "trace-1"
    assert event["attributes"]["trace_id"] == "trace-1"
    assert event["attributes"]["request_id"] == response.headers["x-request-id"]
    assert event["attributes"]["status_code"] == 200
    assert event["attributes"]["caller.name"] == "claude-code"
    assert event["attributes"]["caller.category"] == "agent"
    assert event["attributes"]["caller.agent"] == "claude-code"
    assert event["attributes"]["caller.client_family"] == "anthropic"
    assert event["attributes"]["annotations"]["caller"]["agent"] == "claude-code"
    assert event["attributes"]["metadata"]["lifecycle"] == "request_completed"


def test_rquid_middleware_skips_lifecycle_observability_when_llm_span_exists():
    test_app = FastAPI()
    sink = RecordingObservabilitySink()
    test_app.state.observability_sink = sink
    test_app.add_middleware(RquidMiddleware)

    @test_app.get("/v1/chat/completions")
    async def chat():
        context = get_request_context()
        context.llm_observability_emitted = True
        return {"data": []}

    client = TestClient(test_app)
    response = client.get("/v1/chat/completions")

    assert response.status_code == 200
    assert sink.events == []


def test_rquid_middleware_emits_metrics_for_completed_request():
    test_app = FastAPI()
    sink = RecordingMetricsSink()
    test_app.state.metrics_sink = sink
    test_app.add_middleware(RquidMiddleware)

    @test_app.get("/v1/models")
    async def models():
        return {"data": []}

    client = TestClient(test_app)
    response = client.get("/v1/models")

    assert response.status_code == 200
    assert sink.counters == [
        (
            "gpt2giga_requests_total",
            1,
            {
                "protocol": "openai",
                "route": "/v1/models",
                "method": "GET",
                "status_code": 200,
                "lifecycle": "request_completed",
                "provider": "gigachat",
            },
        )
    ]
    assert len(sink.observations) == 1
    name, value, attributes = sink.observations[0]
    assert name == "gpt2giga_request_duration_seconds"
    assert value >= 0
    assert attributes["route"] == "/v1/models"


def test_rquid_middleware_emits_traffic_event_for_validation_error():
    test_app = FastAPI()
    sink = RecordingTrafficSink()
    test_app.state.traffic_log_sink = sink
    test_app.add_middleware(RequestValidationMiddleware, max_body_bytes=1)
    test_app.add_middleware(RquidMiddleware)

    @test_app.post("/v1/chat/completions")
    async def chat():
        return {"ok": True}

    client = TestClient(test_app)
    response = client.post("/v1/chat/completions", json={"model": "GigaChat"})

    assert response.status_code == 413
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.status_code == 413
    assert event.error_type == "http_413"
    assert event.metadata["lifecycle"] == "request_completed"


@pytest.mark.asyncio
async def test_traffic_log_body_iterator_emits_stream_completed():
    sink = RecordingTrafficSink()
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id=None,
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
    )

    async def stream():
        yield b"data: {}\n\n"

    chunks = [
        chunk
        async for chunk in wrap_traffic_log_body_iterator(
            stream(),
            sink=sink,
            context=context,
            status_code=200,
            is_streaming=True,
        )
    ]

    assert chunks == [b"data: {}\n\n"]
    assert len(sink.events) == 1
    assert sink.events[0].metadata["lifecycle"] == "streaming_completed"


@pytest.mark.asyncio
async def test_traffic_log_body_iterator_emits_stream_aborted():
    sink = RecordingTrafficSink()
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id=None,
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
    )

    async def stream():
        yield b"data: {}\n\n"
        raise asyncio.CancelledError

    chunks = []
    with pytest.raises(asyncio.CancelledError):
        async for chunk in wrap_traffic_log_body_iterator(
            stream(),
            sink=sink,
            context=context,
            status_code=200,
            is_streaming=True,
        ):
            chunks.append(chunk)

    assert chunks == [b"data: {}\n\n"]
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.status_code == 499
    assert event.error_type == "stream_cancelled"
    assert event.metadata["lifecycle"] == "streaming_aborted"
