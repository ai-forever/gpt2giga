from fastapi import FastAPI
from fastapi.testclient import TestClient
from gpt2giga.router import router

app = FastAPI()
app.include_router(router)


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
