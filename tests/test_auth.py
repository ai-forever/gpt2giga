import pytest
from types import SimpleNamespace

from fastapi import HTTPException

from gpt2giga.auth import verify_api_key
from gpt2giga.config import ProxyConfig


def make_request(headers: dict, config: ProxyConfig):
    app = SimpleNamespace(state=SimpleNamespace(config=config))
    req = SimpleNamespace(headers=headers, app=app)
    return req


def test_verify_api_key_success_bearer():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer secret"}, cfg)
    assert verify_api_key(req) == "secret"


def test_verify_api_key_success_x_api_key():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"x-api-key": "secret"}, cfg)
    assert verify_api_key(req) == "secret"


def test_verify_api_key_missing():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({}, cfg)
    with pytest.raises(HTTPException) as ex:
        verify_api_key(req)
    assert ex.value.status_code == 401


def test_verify_api_key_not_configured():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = None
    req = make_request({"authorization": "Bearer any"}, cfg)
    with pytest.raises(HTTPException) as ex:
        verify_api_key(req)
    assert ex.value.status_code == 500


def test_verify_api_key_invalid():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer wrong"}, cfg)
    with pytest.raises(HTTPException) as ex:
        verify_api_key(req)
    assert ex.value.status_code == 401
