from gpt2giga.middleware import PathNormalizationMiddleware
from fastapi import FastAPI
from starlette.testclient import TestClient

app = FastAPI()
app.add_middleware(PathNormalizationMiddleware, valid_roots=["v1"])


@app.get("/v1/test")
def v1_test():
    return {"ok": True}


def test_path_norm_redirect():
    client = TestClient(app)
    resp = client.get("/abc/v1/test")
    # Проверяем перенаправление
    assert resp.status_code == 200
