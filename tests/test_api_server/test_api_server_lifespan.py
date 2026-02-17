from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app


def test_app_lifespan_initializes_state(monkeypatch):
    app = create_app()

    class Dummy:
        def __init__(self, **kwargs):
            pass

        async def aget_models(self):
            return type("R", (), {"data": [], "object_": "list"})()

    # Подменяем клиента GigaChat при старте lifespan
    monkeypatch.setattr("gpt2giga.api_server.GigaChat", lambda **kw: Dummy())

    client = TestClient(app)
    # Триггерим lifespan
    resp = client.get("/health")
    assert resp.status_code == 200
    assert hasattr(app.state, "config")


def test_lifespan_closes_gigachat_client(monkeypatch):
    """Lifespan shutdown must call aclose() on the GigaChat client."""
    closed = []

    class DummyWithClose:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr("gpt2giga.api_server.GigaChat", lambda **kw: DummyWithClose())

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
        "gpt2giga.api_server.GigaChat", lambda **kw: DummyWithBrokenClose()
    )

    app = create_app()
    with TestClient(app):
        TestClient(app).get("/health")
        # App should still work even if close will fail later
