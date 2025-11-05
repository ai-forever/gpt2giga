from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.routers import api_router, system_router

app = FastAPI()
app.include_router(api_router)
app.include_router(system_router)


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_ping_endpoint_get_and_post():
    client = TestClient(app)
    assert client.get("/ping").status_code == 200
    assert client.post("/ping").status_code == 200


def test_unknown_route_returns_404():
    client = TestClient(app)
    resp = client.get("/unknown-route-xyz")
    assert resp.status_code == 404


def test_method_not_allowed_returns_405():
    client = TestClient(app)
    # Для /health определён только GET
    resp = client.post("/health")
    assert resp.status_code == 405
