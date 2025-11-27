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
