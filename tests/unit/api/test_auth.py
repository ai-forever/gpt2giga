import secrets
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fastapi import HTTPException

from gpt2giga.api.dependencies.auth import build_api_key_verifier, verify_api_key
from gpt2giga.api.gemini.request import GeminiAPIError
from gpt2giga.core.config.settings import ProxyConfig


def make_request(
    headers: dict,
    config: ProxyConfig,
    *,
    query_params: dict | None = None,
    path_params: dict | None = None,
    method: str = "GET",
    route_path: str = "/models",
    body: bytes = b"",
):
    app = SimpleNamespace(state=SimpleNamespace(config=config))
    state = SimpleNamespace()
    req = SimpleNamespace(
        headers=headers,
        app=app,
        state=state,
        query_params=query_params or {},
        path_params=path_params or {},
        method=method,
        scope={"route": SimpleNamespace(path_format=route_path)},
        url=SimpleNamespace(path=route_path),
    )

    async def _body():
        return body

    req.body = _body
    return req


@pytest.mark.asyncio
async def test_verify_api_key_success_bearer():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer secret"}, cfg)
    assert await verify_api_key(req) == "secret"


@pytest.mark.asyncio
async def test_verify_api_key_success_x_api_key():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"x-api-key": "secret"}, cfg)
    assert await verify_api_key(req) == "secret"


@pytest.mark.asyncio
async def test_verify_api_key_success_x_goog_api_key():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"x-goog-api-key": "secret"}, cfg)
    assert await verify_api_key(req) == "secret"


@pytest.mark.asyncio
async def test_verify_api_key_success_gemini_query_key():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({}, cfg, query_params={"key": "secret"})
    assert await verify_api_key(req) == "secret"


@pytest.mark.asyncio
async def test_verify_api_key_missing():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({}, cfg)
    with pytest.raises(HTTPException) as ex:
        await verify_api_key(req)
    assert ex.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_api_key_not_configured():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = None
    req = make_request({"authorization": "Bearer any"}, cfg)
    with pytest.raises(HTTPException) as ex:
        await verify_api_key(req)
    assert ex.value.status_code == 500


@pytest.mark.asyncio
async def test_verify_api_key_invalid():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer wrong"}, cfg)
    with pytest.raises(HTTPException) as ex:
        await verify_api_key(req)
    assert ex.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_api_key_uses_constant_time_comparison():
    """Verify that API key comparison uses secrets.compare_digest (constant-time)."""
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer secret"}, cfg)
    with patch(
        "gpt2giga.api.dependencies.auth.secrets.compare_digest",
        wraps=secrets.compare_digest,
    ) as mock_cmp:
        result = await verify_api_key(req)
        mock_cmp.assert_called_once_with("secret", "secret")
    assert result == "secret"


@pytest.mark.asyncio
async def test_verify_api_key_constant_time_rejects_wrong_key():
    """Verify that constant-time comparison correctly rejects invalid keys."""
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "correct-key"
    req = make_request({"authorization": "Bearer wrong-key"}, cfg)
    with patch(
        "gpt2giga.api.dependencies.auth.secrets.compare_digest",
        wraps=secrets.compare_digest,
    ) as mock_cmp:
        with pytest.raises(HTTPException) as ex:
            await verify_api_key(req)
        mock_cmp.assert_called_once_with("wrong-key", "correct-key")
    assert ex.value.status_code == 401


@pytest.mark.asyncio
async def test_scoped_api_key_allows_matching_provider_endpoint_and_model():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "global-secret"
    cfg.proxy_settings.scoped_api_keys = [
        {
            "name": "sdk-openai",
            "key": "scoped-secret",
            "providers": ["openai"],
            "endpoints": ["chat/completions"],
            "models": ["GigaChat-2-Max"],
        }
    ]
    req = make_request(
        {"authorization": "Bearer scoped-secret"},
        cfg,
        method="POST",
        route_path="/v1/chat/completions",
        body=b'{"model":"GigaChat-2-Max","messages":[]}',
    )
    verifier = build_api_key_verifier(provider_name="openai")

    assert await verifier(req) == "scoped-secret"
    assert req.state.api_key_context.name == "sdk-openai"
    assert req.state.api_key_context.source == "scoped"
    assert req.state.api_key_context.endpoint == "chat/completions"
    assert req.state.api_key_context.model == "GigaChat-2-Max"


@pytest.mark.asyncio
async def test_scoped_api_key_rejects_wrong_provider():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "global-secret"
    cfg.proxy_settings.scoped_api_keys = [
        {"key": "scoped-secret", "providers": ["openai"]}
    ]
    req = make_request({"authorization": "Bearer scoped-secret"}, cfg)
    verifier = build_api_key_verifier(provider_name="anthropic")

    with pytest.raises(HTTPException) as ex:
        await verifier(req)

    assert ex.value.status_code == 403
    assert ex.value.detail == "API key is not allowed for this provider"


@pytest.mark.asyncio
async def test_scoped_api_key_rejects_wrong_endpoint():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "global-secret"
    cfg.proxy_settings.scoped_api_keys = [
        {"key": "scoped-secret", "providers": ["openai"], "endpoints": ["responses"]}
    ]
    req = make_request(
        {"authorization": "Bearer scoped-secret"},
        cfg,
        route_path="/chat/completions",
    )
    verifier = build_api_key_verifier(provider_name="openai")

    with pytest.raises(HTTPException) as ex:
        await verifier(req)

    assert ex.value.status_code == 403
    assert ex.value.detail == "API key is not allowed for this endpoint"


@pytest.mark.asyncio
async def test_scoped_api_key_rejects_wrong_model():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "global-secret"
    cfg.proxy_settings.scoped_api_keys = [
        {"key": "scoped-secret", "providers": ["openai"], "models": ["Allowed-Model"]}
    ]
    req = make_request(
        {"authorization": "Bearer scoped-secret"},
        cfg,
        method="POST",
        route_path="/responses",
        body=b'{"model":"Other-Model","input":"hello"}',
    )
    verifier = build_api_key_verifier(provider_name="openai")

    with pytest.raises(HTTPException) as ex:
        await verifier(req)

    assert ex.value.status_code == 403
    assert ex.value.detail == "API key is not allowed for this model"


@pytest.mark.asyncio
async def test_scoped_api_key_is_not_allowed_for_admin_routes():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "global-secret"
    cfg.proxy_settings.scoped_api_keys = [{"key": "scoped-secret"}]
    req = make_request({"authorization": "Bearer scoped-secret"}, cfg)
    verifier = build_api_key_verifier(allow_scoped_keys=False)

    with pytest.raises(HTTPException) as ex:
        await verifier(req)

    assert ex.value.status_code == 403
    assert ex.value.detail == "Scoped API key is not allowed for this route"


@pytest.mark.asyncio
async def test_gemini_scoped_api_key_scope_denial_is_provider_specific():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "global-secret"
    cfg.proxy_settings.scoped_api_keys = [
        {"key": "scoped-secret", "providers": ["gemini"], "models": ["allowed-model"]}
    ]
    req = make_request(
        {"x-goog-api-key": "scoped-secret"},
        cfg,
        method="POST",
        route_path="/v1beta/models/{model}:generateContent",
        path_params={"model": "blocked-model"},
    )
    verifier = build_api_key_verifier(provider_name="gemini", gemini_style=True)

    with pytest.raises(GeminiAPIError) as ex:
        await verifier(req)

    assert ex.value.status_code == 403
    assert ex.value.status == "PERMISSION_DENIED"
    assert ex.value.message == "API key is not allowed for this model"
