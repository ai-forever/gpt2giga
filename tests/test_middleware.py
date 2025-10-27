from fastapi import FastAPI
from starlette.testclient import TestClient

from gpt2giga.middleware import PathNormalizationMiddleware

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


def test_path_norm_preserves_query_params():
    client = TestClient(app)
    resp = client.get("/zzz/v1/test?x=1&y=2")
    assert resp.status_code == 200
    # Убедимся, что конечная ручка получила запрос (просто факт 200 для тестовой ручки)


def test_path_norm_no_redirect_when_already_normalized():
    client = TestClient(app)
    resp = client.get("/v1/test")
    assert resp.status_code == 200


def test_path_norm_no_redirect_for_unknown_root():
    client = TestClient(app)
    # Нет известного корня -> остаётся 404
    resp = client.get("/abc/zzz/test")
    assert resp.status_code == 404
