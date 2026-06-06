from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings


def test_app_lifespan_initializes_state(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_ENABLE_API_KEY_AUTH", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_API_KEY", raising=False)
    config = ProxyConfig(
        proxy=ProxySettings(
            model_max_connections={"GigaChat": 2},
            model_max_connections_default=3,
            model_max_connections_acquire_timeout=0,
        )
    )
    app = create_app(config)

    class Dummy:
        def __init__(self, **kwargs):
            pass

        async def aget_models(self):
            return type("R", (), {"data": [], "object_": "list"})()

        async def aclose(self):
            pass

    # Подменяем клиента GigaChat при старте lifespan
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client", lambda settings: Dummy()
    )

    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert hasattr(app.state, "config")
    assert hasattr(app.state, "model_concurrency_limiter")
    assert app.state.model_concurrency_limiter.limit_for("GigaChat") == 2
    assert app.state.model_concurrency_limiter.limit_for("Other") == 3


def test_lifespan_closes_gigachat_client(monkeypatch):
    """Lifespan shutdown must call aclose() on the GigaChat client."""
    closed = []

    class DummyWithClose:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: DummyWithClose(),
    )

    app = create_app()
    with TestClient(app):
        pass

    assert closed, "GigaChat client aclose() was not called during shutdown"


def test_lifespan_handles_aclose_error(monkeypatch):
    """Lifespan shutdown must not crash if aclose() raises an exception."""

    class DummyWithBrokenClose:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda settings: DummyWithBrokenClose(),
    )

    app = create_app()
    with TestClient(app):
        TestClient(app).get("/health")
        # App should still work even if close will fail later
