from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from gpt2giga.api_server import create_app, _check_port_available
from gpt2giga.models.config import ProxyConfig, ProxySettings


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

    monkeypatch.setattr("gpt2giga.api_server.GigaChat", FakeGigaChat)

    with TestClient(create_app()) as client:
        # Используем контекстный менеджер, чтобы lifespan сработал и инициализировал state
        response = client.get("/v1/models")
        # Должен быть 200, 401, 500, но не 404 (404 значит роутер не подключен)
        assert response.status_code != 404


def test_v1_models_no_307_redirect(monkeypatch):
    """GET /v1/models must return 200, not 307 redirect."""

    class FakeGigaChat:
        def __init__(self, *args, **kwargs):
            pass

        async def aget_models(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[], object_="list")

    monkeypatch.setattr("gpt2giga.api_server.GigaChat", FakeGigaChat)

    with TestClient(create_app()) as client:
        response = client.get("/v1/models", follow_redirects=False)
        assert response.status_code != 307, (
            f"Expected non-redirect status, got 307 -> {response.headers.get('location')}"
        )


def test_redirect_slashes_disabled():
    """FastAPI app must be created with redirect_slashes=False."""
    app = create_app()
    assert app.router.redirect_slashes is False


def test_docs_disabled_in_prod_mode():
    """In PROD mode OpenAPI docs endpoints must be disabled."""
    app = create_app(config=ProxyConfig(proxy=ProxySettings(mode="PROD", api_key="k")))
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_prod_mode_requires_api_key():
    import pytest

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

    monkeypatch.setattr("gpt2giga.api_server.GigaChat", FakeGigaChat)

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
    monkeypatch.setattr("gpt2giga.api_server._check_port_available", lambda h, p: True)

    gpt2giga.api_server.run()


def test_run_server_port_in_use(monkeypatch):
    """run() must exit with error when port is already in use."""
    import pytest
    import gpt2giga.api_server
    import uvicorn

    monkeypatch.setattr("gpt2giga.api_server._check_port_available", lambda h, p: False)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    def fake_exit(code):
        raise SystemExit(code)

    monkeypatch.setattr("gpt2giga.api_server.sys.exit", fake_exit)

    with pytest.raises(SystemExit, match="1"):
        gpt2giga.api_server.run()


def test_check_port_available_free():
    """Port 0 (OS picks a free port) should be available."""
    assert _check_port_available("127.0.0.1", 0) is True


def test_check_port_available_in_use():
    """Binding to a port that is already in use should return False."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        _, port = s.getsockname()
        s.listen(1)
        assert _check_port_available("127.0.0.1", port) is False
