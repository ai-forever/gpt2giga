from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from gpt2giga.app.factory import create_app
from gpt2giga.app.run import run as run_app
from gpt2giga.core.app_meta import check_port_available
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


class _FakeGigaChat:
    def __init__(self, *args, **kwargs):
        pass

    async def aget_models(self):
        return SimpleNamespace(data=[], object_="list")

    async def aclose(self):
        return None


def _default_config() -> ProxyConfig:
    return ProxyConfig(proxy=ProxySettings())


def test_root_redirect():
    app = create_app(config=_default_config())
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


def test_root_head_allowed():
    app = create_app(config=_default_config())
    client = TestClient(app)
    response = client.head("/")
    assert response.status_code == 200


def test_cors_headers_present():
    app = create_app(config=_default_config())
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

    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", FakeGigaChat)

    with TestClient(create_app(config=_default_config())) as client:
        # Используем контекстный менеджер, чтобы lifespan сработал и инициализировал state
        response = client.get("/v1/models")
        # Должен быть 200, 401, 500, но не 404 (404 значит роутер не подключен)
        assert response.status_code != 404


def test_v1_litellm_router_is_registered(monkeypatch):
    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", FakeGigaChat)

    with TestClient(create_app(config=_default_config())) as client:
        response = client.get("/v1/model/info")
        assert response.status_code != 404


def test_v1beta_gemini_router_is_registered(monkeypatch):
    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", FakeGigaChat)

    with TestClient(create_app(config=_default_config())) as client:
        response = client.get("/v1beta/models")
        assert response.status_code != 404


def test_v1_models_no_307_redirect(monkeypatch):
    """GET /v1/models must return 200, not 307 redirect."""

    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", FakeGigaChat)

    with TestClient(create_app(config=_default_config())) as client:
        response = client.get("/v1/models", follow_redirects=False)
        assert response.status_code != 307, (
            f"Expected non-redirect status, got 307 -> {response.headers.get('location')}"
        )


def test_redirect_slashes_disabled():
    """FastAPI app must be created with redirect_slashes=False."""
    app = create_app(config=_default_config())
    assert app.router.redirect_slashes is False


def test_docs_disabled_in_prod_mode():
    """In PROD mode OpenAPI docs endpoints must be disabled."""
    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_openapi_json_available_in_dev_mode():
    """In DEV mode OpenAPI schema must be generated successfully."""
    app = create_app(config=_default_config())
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/chat/completions" in schema["paths"]
    assert "/messages" in schema["paths"]
    assert "/v1beta/models/{model}:generateContent" in schema["paths"]
    assert "/metrics" in schema["paths"]
    assert "/admin/api/runtime" in schema["paths"]
    assert "/admin/api/metrics" in schema["paths"]
    assert "/admin/api/requests/recent" in schema["paths"]
    assert "/admin/api/errors/recent" in schema["paths"]
    assert "/logs" not in schema["paths"]
    chat_examples = schema["paths"]["/chat/completions"]["post"]["requestBody"][
        "content"
    ]["application/json"]["examples"]
    assert "minimal" in chat_examples


def test_prod_mode_requires_api_key(monkeypatch):
    import pytest

    monkeypatch.delenv("GPT2GIGA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API key must be configured"):
        create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD")))


def test_prod_mode_forces_auth_dependency():
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(
                mode="PROD",
                api_key="k",
                enabled_providers=["openai", "anthropic", "gemini"],
            )
        )
    )
    client = TestClient(app)
    response = client.get("/models")
    assert response.status_code == 401


def test_prod_mode_disables_admin_and_legacy_logs_routes():
    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    client = TestClient(app)
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/api/runtime").status_code == 404
    assert client.get("/logs").status_code == 404
    assert client.get("/logs/stream").status_code == 404
    assert client.get("/logs/html").status_code == 404


def test_prod_mode_keeps_metrics_route_but_requires_api_key(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    client = TestClient(app)

    assert client.get("/metrics").status_code == 401


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

    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", FakeGigaChat)

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

    assert client.get("/admin").status_code == 401
    assert client.get("/admin/api/runtime").status_code == 401
    assert client.get("/admin/api/logs").status_code == 401
    assert client.get("/logs").status_code == 401
    assert client.get("/logs/stream").status_code == 401
    assert client.get("/logs/html").status_code == 401


def test_scoped_api_key_allows_matching_provider_route(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            enable_api_key_auth=True,
            api_key="global-secret",
            scoped_api_keys=[
                {
                    "name": "sdk-openai",
                    "key": "scoped-secret",
                    "providers": ["openai"],
                    "endpoints": ["models"],
                }
            ],
        )
    )
    with TestClient(create_app(config=cfg)) as client:
        response = client.get(
            "/v1/models", headers={"Authorization": "Bearer scoped-secret"}
        )

    assert response.status_code == 200


def test_scoped_api_key_cannot_access_admin_routes(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            enable_api_key_auth=True,
            api_key="global-secret",
            scoped_api_keys=[{"key": "scoped-secret", "providers": ["openai"]}],
        )
    )
    app = create_app(config=cfg)
    client = TestClient(app)

    response = client.get(
        "/admin/api/runtime", headers={"Authorization": "Bearer scoped-secret"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Scoped API key is not allowed for this route"


def test_governance_limit_blocks_second_scoped_openai_request(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)
    monkeypatch.setattr("gpt2giga.app.governance.time", lambda: 1_800_000_000)

    cfg = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            enable_api_key_auth=True,
            api_key="global-secret",
            scoped_api_keys=[
                {
                    "name": "sdk-openai",
                    "key": "scoped-secret",
                    "providers": ["openai"],
                    "endpoints": ["models"],
                }
            ],
            governance_limits=[
                {
                    "name": "sdk-openai-models",
                    "scope": "api_key",
                    "providers": ["openai"],
                    "endpoints": ["models"],
                    "window_seconds": 60,
                    "max_requests": 1,
                }
            ],
        )
    )
    with TestClient(create_app(config=cfg)) as client:
        first = client.get(
            "/v1/models", headers={"Authorization": "Bearer scoped-secret"}
        )
        second = client.get(
            "/v1/models", headers={"Authorization": "Bearer scoped-secret"}
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"


def test_openai_provider_group_mounts_litellm_routes(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(proxy=ProxySettings(enabled_providers=["openai"]))
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/v1/models").status_code != 404
        assert client.get("/v1/model/info").status_code != 404
        assert client.get("/messages").status_code == 404
        assert client.get("/v1beta/models").status_code == 404


def test_anthropic_provider_can_be_enabled_independently(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(proxy=ProxySettings(enabled_providers=["anthropic"]))
    with TestClient(create_app(config=cfg)) as client:
        assert (
            client.post("/messages", json={"model": "test", "messages": []}).status_code
            != 404
        )
        assert client.get("/v1/models").status_code == 404
        assert client.get("/v1/model/info").status_code == 404
        assert client.get("/v1beta/models").status_code == 404


def test_gemini_provider_can_be_enabled_independently(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(proxy=ProxySettings(enabled_providers=["gemini"]))
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/v1beta/models").status_code != 404
        assert client.get("/v1/models").status_code == 404
        assert client.get("/v1/model/info").status_code == 404
        assert (
            client.post("/messages", json={"model": "test", "messages": []}).status_code
            == 404
        )


def test_all_provider_groups_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(proxy=ProxySettings(enabled_providers=["all"]))
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/v1/models").status_code != 404
        assert client.get("/v1/model/info").status_code != 404
        assert (
            client.post("/messages", json={"model": "test", "messages": []}).status_code
            != 404
        )
        assert client.get("/v1beta/models").status_code != 404


def test_openapi_only_includes_enabled_providers(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(proxy=ProxySettings(enabled_providers=["openai"]))
    client = TestClient(create_app(config=cfg))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/chat/completions" in schema["paths"]
    assert "/model/info" in schema["paths"]
    assert "/messages" not in schema["paths"]
    assert "/v1beta/models/{model}:generateContent" not in schema["paths"]


def test_admin_recent_requests_endpoint_collects_runtime_events(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    with TestClient(create_app(config=_default_config())) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/admin/api/requests/recent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "requests"
    assert any(event["endpoint"] == "/health" for event in payload["events"])


def test_admin_recent_errors_endpoint_collects_404_events(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    with TestClient(create_app(config=_default_config())) as client:
        assert client.get("/does-not-exist").status_code == 404
        response = client.get("/admin/api/errors/recent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "errors"
    assert any(event["status_code"] == 404 for event in payload["events"])


def test_sqlite_runtime_backend_works_through_app_lifespan(tmp_path, monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(
        proxy=ProxySettings(
            runtime_store_backend="sqlite",
            runtime_store_dsn=str(tmp_path / "runtime.sqlite3"),
            runtime_store_namespace="lifespan-tests",
        )
    )

    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/health").status_code == 200
        response = client.get(
            "/admin/api/requests/recent", params={"provider": "system"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "requests"
    assert any(event["endpoint"] == "/health" for event in payload["events"])


def test_metrics_endpoints_expose_prometheus_payload(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    with TestClient(create_app(config=_default_config())) as client:
        assert client.get("/health").status_code == 200
        metrics = client.get("/metrics")
        admin_metrics = client.get("/admin/api/metrics")

    assert metrics.status_code == 200
    assert admin_metrics.status_code == 200
    assert "version=0.0.4" in metrics.headers["content-type"]
    assert (
        'gpt2giga_http_requests_total{provider="system",endpoint="/health",'
        'method="GET",status_code="200"} 1'
    ) in metrics.text
    assert metrics.text == admin_metrics.text


def test_metrics_endpoints_return_404_when_prometheus_sink_disabled(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(proxy=ProxySettings(observability_sinks=[]))
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/metrics").status_code == 404
        assert client.get("/admin/api/metrics").status_code == 404


def test_metrics_endpoints_return_404_when_telemetry_disabled(monkeypatch):
    monkeypatch.setattr("gpt2giga.providers.gigachat.client.GigaChat", _FakeGigaChat)

    cfg = ProxyConfig(proxy=ProxySettings(enable_telemetry=False))
    with TestClient(create_app(config=cfg)) as client:
        assert client.get("/metrics").status_code == 404
        assert client.get("/admin/api/metrics").status_code == 404


def test_run_server(monkeypatch):
    run_app(
        uvicorn_runner=lambda *args, **kwargs: None,
        port_checker=lambda h, p: True,
    )


def test_run_server_port_in_use(monkeypatch):
    """run() must exit with error when port is already in use."""
    import pytest

    def fake_exit(code):
        raise SystemExit(code)

    with pytest.raises(SystemExit, match="1"):
        run_app(
            uvicorn_runner=lambda *args, **kwargs: None,
            port_checker=lambda h, p: False,
            exit_func=fake_exit,
        )


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
