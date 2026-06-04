from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gpt2giga.app_state import get_model_concurrency_limiter
from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter


def test_get_model_concurrency_limiter_returns_app_state_limiter() -> None:
    app = FastAPI()
    limiter = ModelConcurrencyLimiter({"GigaChat": 1})
    app.state.model_concurrency_limiter = limiter

    @app.get("/limiter")
    def read_limiter(request: Request):
        resolved = get_model_concurrency_limiter(request)
        assert resolved is limiter
        return {"limit": resolved.limit_for("GigaChat")}

    client = TestClient(app)
    response = client.get("/limiter")

    assert response.status_code == 200
    assert response.json() == {"limit": 1}
