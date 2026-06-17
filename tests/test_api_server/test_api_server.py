from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from gpt2giga.api_server import create_app
from gpt2giga.app.factory import create_app as create_modular_app
from gpt2giga.common.app_meta import check_port_available
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.openapi_tags import (
    OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION,
    OPENAPI_TAG_ADMIN_TRAFFIC_LOGS,
    OPENAPI_TAG_ANTHROPIC_MESSAGES,
    OPENAPI_TAG_GEMINI_EMBEDDINGS,
    OPENAPI_TAG_GEMINI_GENERATE_CONTENT,
    OPENAPI_TAG_GEMINI_MODELS,
    OPENAPI_TAG_LITELLM_MODEL_INFO,
    OPENAPI_TAG_OPENAI_CHAT_COMPLETIONS,
    OPENAPI_TAG_OPENAI_EMBEDDINGS,
    OPENAPI_TAG_OPENAI_MODELS,
    OPENAPI_TAG_OPENAI_RESPONSES,
    OPENAPI_TAG_SYSTEM_HEALTH,
    OPENAPI_TAG_SYSTEM_LOGS,
)
from gpt2giga.protocols.gemini import GeminiProtocolAdapter
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.sinks.logs.noop import NoopTrafficLogSink
from gpt2giga.sinks.metrics.noop import NoopMetricsSink
from gpt2giga.sinks.observability.noop import NoopObservabilitySink


def test_legacy_create_app_facade_uses_modular_factory():
    assert create_app is create_modular_app


def test_root_redirect():
    app = create_app()
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


def test_cors_headers_present():
    app = create_app()
    client = TestClient(app)
    response = client.options("/health", headers={"Origin": "http://example.com"})
    assert response.status_code == 405


def test_v1_prefix_router_is_registered(monkeypatch):
    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: FakeGigaChat(),
    )

    with TestClient(create_app()) as client:
        # Используем контекстный менеджер, чтобы lifespan сработал и инициализировал state
        response = client.get("/v1/models")
        # Должен быть 200, 401, 500, но не 404 (404 значит роутер не подключен)
        assert response.status_code != 404


def test_v2_prefix_router_is_registered(monkeypatch):
    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: FakeGigaChat(),
    )

    with TestClient(create_app()) as client:
        response = client.get("/v2/models")
        assert response.status_code != 404


def test_v1_litellm_router_is_registered(monkeypatch):
    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: FakeGigaChat(),
    )

    with TestClient(create_app()) as client:
        response = client.get("/v1/model/info")
        assert response.status_code != 404


def test_v1_models_no_307_redirect(monkeypatch):
    """GET /v1/models must return 200, not 307 redirect."""

    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: FakeGigaChat(),
    )

    with TestClient(create_app()) as client:
        response = client.get("/v1/models", follow_redirects=False)
        assert response.status_code != 307, (
            f"Expected non-redirect status, got 307 -> {response.headers.get('location')}"
        )


def test_redirect_slashes_disabled():
    """FastAPI app must be created with redirect_slashes=False."""
    app = create_app()
    assert app.router.redirect_slashes is False


def test_app_factory_creates_default_extension_sinks():
    app = create_app()

    assert isinstance(app.state.traffic_log_sink, NoopTrafficLogSink)
    assert isinstance(app.state.observability_sink, NoopObservabilitySink)
    assert isinstance(app.state.metrics_sink, NoopMetricsSink)


def test_app_factory_creates_openai_protocol_adapter():
    app = create_app()

    assert isinstance(app.state.openai_protocol_adapter, OpenAIProtocolAdapter)


def test_app_factory_creates_gemini_protocol_adapter():
    app = create_app()

    assert isinstance(app.state.gemini_protocol_adapter, GeminiProtocolAdapter)


def test_app_with_unavailable_postgres_traffic_sink_still_serves_requests(
    monkeypatch,
):
    class FakeGigaChat:
        async def aclose(self):
            return None

    async def broken_pool(self):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: FakeGigaChat(),
    )
    monkeypatch.setattr(
        "gpt2giga.sinks.logs.postgres.PostgresTrafficLogSink._create_pool",
        broken_pool,
    )
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                traffic_log_enabled=True,
                traffic_log_sink="postgres",
                traffic_log_postgres_dsn="postgresql://user:pass@127.0.0.1:1/gpt2giga",
                traffic_log_flush_interval_ms=10,
            )
        )
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_docs_disabled_in_prod_mode():
    """In PROD mode OpenAPI docs endpoints must be disabled."""
    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_openapi_tags_group_routes_by_provider_and_endpoint_type():
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                mode="DEV",
                admin_api_enabled=True,
                debug_translate_enabled=True,
                admin_api_key="admin",
            )
        )
    )
    schema = app.openapi()

    expected_route_tags = {
        ("post", "/chat/completions"): [OPENAPI_TAG_OPENAI_CHAT_COMPLETIONS],
        ("post", "/v1/chat/completions"): [OPENAPI_TAG_OPENAI_CHAT_COMPLETIONS],
        ("post", "/v2/responses"): [OPENAPI_TAG_OPENAI_RESPONSES],
        ("post", "/embeddings"): [OPENAPI_TAG_OPENAI_EMBEDDINGS],
        ("get", "/models"): [OPENAPI_TAG_OPENAI_MODELS],
        ("post", "/models/{model}:generateContent"): [
            OPENAPI_TAG_GEMINI_GENERATE_CONTENT
        ],
        ("post", "/v1/models/{model}:generateContent"): [
            OPENAPI_TAG_GEMINI_GENERATE_CONTENT
        ],
        ("post", "/v2/models/{model}:generateContent"): [
            OPENAPI_TAG_GEMINI_GENERATE_CONTENT
        ],
        ("post", "/v1beta/models/{model}:generateContent"): [
            OPENAPI_TAG_GEMINI_GENERATE_CONTENT
        ],
        ("post", "/v1/v1beta/models/{model}:generateContent"): [
            OPENAPI_TAG_GEMINI_GENERATE_CONTENT
        ],
        ("post", "/v2/v1beta/models/{model}:generateContent"): [
            OPENAPI_TAG_GEMINI_GENERATE_CONTENT
        ],
        ("post", "/v1/models/{model}:embedContent"): [OPENAPI_TAG_GEMINI_EMBEDDINGS],
        ("post", "/v2/models/{model}:embedContent"): [OPENAPI_TAG_GEMINI_EMBEDDINGS],
        ("post", "/v1beta/models/{model}:embedContent"): [
            OPENAPI_TAG_GEMINI_EMBEDDINGS
        ],
        ("post", "/v1/v1beta/models/{model}:embedContent"): [
            OPENAPI_TAG_GEMINI_EMBEDDINGS
        ],
        ("post", "/v2/v1beta/models/{model}:embedContent"): [
            OPENAPI_TAG_GEMINI_EMBEDDINGS
        ],
        ("get", "/v1beta/models"): [OPENAPI_TAG_GEMINI_MODELS],
        ("get", "/v1/v1beta/models"): [OPENAPI_TAG_GEMINI_MODELS],
        ("get", "/v2/v1beta/models"): [OPENAPI_TAG_GEMINI_MODELS],
        ("post", "/messages"): [OPENAPI_TAG_ANTHROPIC_MESSAGES],
        ("post", "/v1/messages/count_tokens"): [OPENAPI_TAG_ANTHROPIC_MESSAGES],
        ("get", "/model/info"): [OPENAPI_TAG_LITELLM_MODEL_INFO],
        ("get", "/health"): [OPENAPI_TAG_SYSTEM_HEALTH],
        ("get", "/logs"): [OPENAPI_TAG_SYSTEM_LOGS],
        ("get", "/logs/html"): [OPENAPI_TAG_SYSTEM_LOGS],
        ("get", "/_admin/logs"): [OPENAPI_TAG_ADMIN_TRAFFIC_LOGS],
        ("post", "/_debug/translate"): [OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION],
    }
    for (method, path), tags in expected_route_tags.items():
        assert schema["paths"][path][method]["tags"] == tags

    legacy_tags = {
        "OpenAI",
        "Anthropic",
        "LiteLLM",
        "V1",
        "V2",
        "V1 Anthropic",
        "V2 Anthropic",
        "V1 LiteLLM",
        "V2 LiteLLM",
        "System logs",
        "HTML logs",
        "Admin",
        "Debug",
    }
    operation_tags = {
        tag
        for methods in schema["paths"].values()
        for operation in methods.values()
        for tag in operation.get("tags", [])
    }

    assert operation_tags.isdisjoint(legacy_tags)
    assert {tag["name"] for tag in schema["tags"]} == operation_tags
    assert all(" / " in tag for tag in operation_tags)
    assert all(
        len(operation.get("tags", [])) == 1
        for methods in schema["paths"].values()
        for operation in methods.values()
    )


def test_prod_mode_requires_api_key(monkeypatch):
    import pytest

    monkeypatch.delenv("GPT2GIGA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API key must be configured"):
        create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD")))


def test_prod_mode_forces_auth_dependency():
    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    client = TestClient(app)
    response = client.get("/models")
    assert response.status_code == 401


def test_prod_mode_disables_logs_router():
    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    client = TestClient(app)
    assert client.get("/logs").status_code == 404
    assert client.get("/logs/stream").status_code == 404
    assert client.get("/logs/html").status_code == 404


def test_prod_mode_cors_is_hardened():
    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    cors = next((m for m in app.user_middleware if m.cls is CORSMiddleware), None)
    assert cors is not None
    assert cors.kwargs["allow_credentials"] is False
    assert "*" not in cors.kwargs["allow_origins"]


def test_non_prod_logs_endpoints_require_api_key_when_enabled(tmp_path, monkeypatch):
    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: FakeGigaChat(),
    )

    log_file = tmp_path / "gpt2giga.log"
    log_file.write_text("INFO: log line\n")

    cfg = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            enable_api_key_auth=True,
            api_key="k",
            log_filename=str(log_file),
        )
    )
    app = create_app(config=cfg)
    client = TestClient(app)

    assert client.get("/logs").status_code == 401
    assert client.get("/logs/stream").status_code == 401
    assert client.get("/logs/html").status_code == 401


def test_run_server(monkeypatch):
    import gpt2giga.api_server
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr("gpt2giga.api_server.check_port_available", lambda h, p: True)

    gpt2giga.api_server.run()


def test_run_server_port_in_use(monkeypatch):
    """run() must exit with error when port is already in use."""
    import pytest
    import gpt2giga.api_server
    import uvicorn

    monkeypatch.setattr("gpt2giga.api_server.check_port_available", lambda h, p: False)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    def fake_exit(code):
        raise SystemExit(code)

    monkeypatch.setattr("gpt2giga.api_server.sys.exit", fake_exit)

    with pytest.raises(SystemExit, match="1"):
        gpt2giga.api_server.run()


def test_check_port_available_free():
    """Port 0 (OS picks a free port) should be available."""
    assert check_port_available("127.0.0.1", 0) is True


def test_check_port_available_in_use():
    """Binding to a port that is already in use should return False."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        _, port = s.getsockname()
        s.listen(1)
        assert check_port_available("127.0.0.1", port) is False
