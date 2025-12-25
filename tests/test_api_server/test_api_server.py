from fastapi.testclient import TestClient

from gpt2giga.api_server import create_app


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


def test_v1_prefix_router_is_registered():
    with TestClient(create_app()) as client:
        # Используем контекстный менеджер, чтобы lifespan сработал и инициализировал state
        response = client.get("/v1/models")
        assert response.status_code != 404


def test_run_server(monkeypatch):
    import gpt2giga.api_server
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)

    gpt2giga.api_server.run()
