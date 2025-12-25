from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient

from gpt2giga.middlewares.pass_token import PassTokenMiddleware
from gpt2giga.middlewares.path_normalizer import PathNormalizationMiddleware

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


def test_pass_token_middleware(monkeypatch):
    test_app = FastAPI()
    test_app.add_middleware(PassTokenMiddleware)

    # Mock settings
    config = SimpleNamespace(proxy_settings=SimpleNamespace(pass_token=True))
    test_app.state.config = config

    # Mock GigaChat client
    client_mock = SimpleNamespace(_settings=SimpleNamespace())
    test_app.state.gigachat_client = client_mock

    # Mock logger
    test_app.state.logger = MagicMock()

    @test_app.get("/check")
    def check_token():
        return {"ok": True}

    client = TestClient(test_app)

    # Test valid token
    resp = client.get("/check", headers={"Authorization": "Bearer giga-auth-mytoken"})
    assert resp.status_code == 200
    # pass_token_to_gigachat logic should put 'mytoken' into access_token
    assert client_mock._settings.access_token == "mytoken"

    # Test error handling
    # Mock pass_token_to_gigachat to raise exception
    def broken_pass(*args):
        raise ValueError("Boom")

    monkeypatch.setattr(
        "gpt2giga.middlewares.pass_token.pass_token_to_gigachat", broken_pass
    )

    resp = client.get("/check", headers={"Authorization": "Bearer giga-auth-fail"})
    assert resp.status_code == 200
    test_app.state.logger.warning.assert_called()

    # Test pass_token disabled
    config.proxy_settings.pass_token = False
    test_app.state.logger.warning.reset_mock()
    resp = client.get("/check", headers={"Authorization": "Bearer giga-auth-ignored"})
    assert resp.status_code == 200
    # Nothing should happen, no warning
    test_app.state.logger.warning.assert_not_called()
