import secrets
from unittest.mock import patch

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


def test_verify_api_key_uses_constant_time_comparison():
    """Verify that API key comparison uses secrets.compare_digest (constant-time)."""
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer secret"}, cfg)
    with patch(
        "gpt2giga.auth.secrets.compare_digest", wraps=secrets.compare_digest
    ) as mock_cmp:
        result = verify_api_key(req)
        mock_cmp.assert_called_once_with("secret", "secret")
    assert result == "secret"


def test_verify_api_key_constant_time_rejects_wrong_key():
    """Verify that constant-time comparison correctly rejects invalid keys."""
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "correct-key"
    req = make_request({"authorization": "Bearer wrong-key"}, cfg)
    with patch(
        "gpt2giga.auth.secrets.compare_digest", wraps=secrets.compare_digest
    ) as mock_cmp:
        with pytest.raises(HTTPException) as ex:
            verify_api_key(req)
        mock_cmp.assert_called_once_with("wrong-key", "correct-key")
    assert ex.value.status_code == 401
