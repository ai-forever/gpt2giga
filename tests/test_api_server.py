from gpt2giga.api_server import create_app
from fastapi.testclient import TestClient


def test_root_redirect():
    app = create_app()
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
