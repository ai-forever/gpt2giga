from fastapi.testclient import TestClient

from gpt2giga.app.factory import create_app


def test_app_lifespan_initializes_state(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_ENABLE_API_KEY_AUTH", raising=False)
    monkeypatch.delenv("GPT2GIGA_MODE", raising=False)
    monkeypatch.delenv("GPT2GIGA_API_KEY", raising=False)
    app = create_app()

    class Dummy:
        def __init__(self, **kwargs):
            pass

        async def aget_models(self):
            return type("R", (), {"data": [], "object_": "list"})()

    # Подменяем клиента GigaChat при старте lifespan
    monkeypatch.setattr(
        "gpt2giga.providers.gigachat.client.GigaChat", lambda **kw: Dummy()
    )

    with TestClient(app) as client:
        # Триггерим lifespan
        resp = client.get("/health")
        assert resp.status_code == 200
        assert hasattr(app.state, "config")
        assert hasattr(app.state, "services")
        assert hasattr(app.state, "stores")
        assert hasattr(app.state, "providers")
        assert app.state.providers.gigachat_client is not None


def test_lifespan_closes_gigachat_client(monkeypatch):
    """Lifespan shutdown must call aclose() on the GigaChat client."""
    closed = []

    class DummyWithClose:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(
        "gpt2giga.providers.gigachat.client.GigaChat",
        lambda **kw: DummyWithClose(),
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
        "gpt2giga.providers.gigachat.client.GigaChat",
        lambda **kw: DummyWithBrokenClose(),
    )

    app = create_app()
    with TestClient(app):
        TestClient(app).get("/health")
        # App should still work even if close will fail later
