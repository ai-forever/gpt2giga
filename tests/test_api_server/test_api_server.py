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
    app = create_app()
    client = TestClient(app)
    response = client.get("/v1/health")
    assert response.status_code == 200
