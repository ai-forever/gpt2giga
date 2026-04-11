from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.testclient import TestClient

from gpt2giga.api.middleware.observability import ObservabilityMiddleware
from gpt2giga.api.middleware.pass_token import PassTokenMiddleware
from gpt2giga.api.middleware.path_normalizer import PathNormalizationMiddleware
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.app.observability import (
    set_request_audit_error,
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.core.config.settings import ProxyConfig

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


def test_path_norm_keeps_v1beta_prefix():
    test_app = FastAPI()
    test_app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=["v1", "v1beta", "models"],
    )

    @test_app.get("/v1beta/models")
    def list_models():
        return {"ok": True}

    client = TestClient(test_app)
    resp = client.get("/proxy/v1beta/models")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


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
    monkeypatch.setattr("gpt2giga.providers.gigachat.auth.GigaChat", FakeGigaChat)

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
        "gpt2giga.api.middleware.pass_token.create_gigachat_client_for_request",
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


def test_observability_middleware_records_recent_requests_and_errors():
    test_app = FastAPI()
    ensure_runtime_dependencies(test_app.state, config=ProxyConfig())
    test_app.add_middleware(ObservabilityMiddleware)

    @test_app.get("/ok", tags=["OpenAI"])
    def ok():
        return {"ok": True}

    @test_app.get("/boom", tags=["OpenAI"])
    def boom():
        raise HTTPException(status_code=418, detail="teapot")

    client = TestClient(test_app)

    assert client.get("/ok").status_code == 200
    assert client.get("/boom").status_code == 418

    recent_requests = test_app.state.stores.recent_requests.recent()
    recent_errors = test_app.state.stores.recent_errors.recent()

    assert [item["endpoint"] for item in recent_requests] == ["/ok", "/boom"]
    assert recent_requests[0]["status_code"] == 200
    assert recent_requests[1]["status_code"] == 418
    assert recent_requests[1]["error_type"] == "HTTP_418"
    assert recent_errors == [recent_requests[1]]
    assert test_app.state.stores.usage_by_provider["openai"]["request_count"] == 2
    assert test_app.state.stores.usage_by_provider["openai"]["error_count"] == 1


def test_observability_middleware_ignores_admin_surface():
    test_app = FastAPI()
    ensure_runtime_dependencies(test_app.state, config=ProxyConfig())
    test_app.add_middleware(ObservabilityMiddleware)

    @test_app.get("/admin/echo")
    def admin_echo():
        return {"ok": True}

    client = TestClient(test_app)

    assert client.get("/admin/echo").status_code == 200
    assert test_app.state.stores.recent_requests.recent() == []


def test_observability_middleware_records_stream_metadata_and_stream_errors():
    test_app = FastAPI()
    ensure_runtime_dependencies(test_app.state, config=ProxyConfig())
    test_app.add_middleware(ObservabilityMiddleware)

    @test_app.get("/stream")
    async def stream(request: Request):
        set_request_audit_model(request, "gpt-x")

        async def gen():
            set_request_audit_usage(
                request,
                {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            )
            set_request_audit_error(request, "RateLimitError")
            yield "data: partial\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    client = TestClient(test_app)

    response = client.get("/stream")

    assert response.status_code == 200
    assert "partial" in response.text
    recent_requests = test_app.state.stores.recent_requests.recent()
    recent_errors = test_app.state.stores.recent_errors.recent()

    assert len(recent_requests) == 1
    event = recent_requests[0]
    assert event["model"] == "gpt-x"
    assert event["token_usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    assert event["stream_duration_ms"] is not None
    assert event["error_type"] == "RateLimitError"
    assert recent_errors == [event]


def test_observability_middleware_aggregates_usage_by_api_key_and_provider():
    test_app = FastAPI()
    ensure_runtime_dependencies(test_app.state, config=ProxyConfig())
    test_app.add_middleware(ObservabilityMiddleware)

    @test_app.post("/chat/completions", tags=["OpenAI"])
    async def chat(request: Request):
        request.state.api_key_context = SimpleNamespace(
            name="sdk-openai",
            source="scoped",
        )
        set_request_audit_model(request, "GigaChat-2-Max")
        set_request_audit_usage(
            request,
            {
                "prompt_tokens": 7,
                "completion_tokens": 5,
                "total_tokens": 12,
            },
        )
        return {"ok": True}

    client = TestClient(test_app)

    response = client.post("/chat/completions", json={"model": "GigaChat-2-Max"})

    assert response.status_code == 200
    api_key_usage = test_app.state.stores.usage_by_api_key["sdk-openai"]
    provider_usage = test_app.state.stores.usage_by_provider["openai"]
    assert api_key_usage["source"] == "scoped"
    assert api_key_usage["request_count"] == 1
    assert api_key_usage["total_tokens"] == 12
    assert api_key_usage["providers"]["openai"]["request_count"] == 1
    assert api_key_usage["models"]["GigaChat-2-Max"]["total_tokens"] == 12
    assert provider_usage["request_count"] == 1
    assert provider_usage["api_keys"]["sdk-openai"]["source"] == "scoped"
    assert provider_usage["endpoints"]["/chat/completions"]["request_count"] == 1
