from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from fastapi import HTTPException

from gpt2giga.api.dependencies.governance import build_governance_verifier
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.app.observability import record_request_event
from gpt2giga.core.config.settings import ProxyConfig, ProxySettings


def make_request(
    config: ProxyConfig,
    *,
    route_path: str,
    provider_name: str,
    method: str = "GET",
    body: bytes = b"",
    api_key_name: str | None = None,
):
    app = SimpleNamespace(state=SimpleNamespace())
    ensure_runtime_dependencies(app.state, config=config)
    state = SimpleNamespace()
    if api_key_name is not None:
        state.api_key_context = SimpleNamespace(name=api_key_name, source="scoped")
    req = SimpleNamespace(
        app=app,
        state=state,
        headers={},
        query_params={},
        path_params={},
        method=method,
        scope={"route": SimpleNamespace(path_format=route_path)},
        url=SimpleNamespace(path=route_path),
    )

    async def _body():
        return body

    req.body = _body
    return req, build_governance_verifier(provider_name=provider_name)


@pytest.mark.asyncio
async def test_api_key_governance_request_limit_blocks_second_request(monkeypatch):
    monkeypatch.setattr("gpt2giga.app.governance.time", lambda: 1_800_000_000)
    config = ProxyConfig(
        proxy=ProxySettings(
            governance_limits=[
                {
                    "name": "sdk-models",
                    "scope": "api_key",
                    "providers": ["openai"],
                    "endpoints": ["models"],
                    "window_seconds": 60,
                    "max_requests": 1,
                }
            ]
        )
    )
    request, verifier = make_request(
        config,
        route_path="/v1/models",
        provider_name="openai",
        api_key_name="sdk-openai",
    )

    await verifier(request)
    with pytest.raises(HTTPException) as ex:
        await verifier(request)

    assert ex.value.status_code == 429
    assert ex.value.headers["Retry-After"] == "60"
    assert "sdk-openai" in str(ex.value.detail)


@pytest.mark.asyncio
async def test_provider_governance_token_quota_uses_recorded_usage(monkeypatch):
    fixed_now = 1_800_000_005
    monkeypatch.setattr("gpt2giga.app.governance.time", lambda: fixed_now)
    config = ProxyConfig(
        proxy=ProxySettings(
            governance_limits=[
                {
                    "name": "openai-chat-quota",
                    "scope": "provider",
                    "providers": ["openai"],
                    "endpoints": ["chat/completions"],
                    "models": ["GigaChat-2-Max"],
                    "window_seconds": 60,
                    "max_total_tokens": 10,
                }
            ]
        )
    )
    request, verifier = make_request(
        config,
        route_path="/v1/chat/completions",
        provider_name="openai",
        method="POST",
        body=b'{"model":"GigaChat-2-Max","messages":[]}',
    )

    record_request_event(
        request.app.state,
        {
            "created_at": datetime.fromtimestamp(fixed_now, UTC).isoformat(),
            "request_id": "req-1",
            "provider": "openai",
            "endpoint": "/chat/completions",
            "method": "POST",
            "path": "/v1/chat/completions",
            "status_code": 200,
            "duration_ms": 10.0,
            "stream_duration_ms": None,
            "client_ip": "127.0.0.1",
            "model": "GigaChat-2-Max",
            "token_usage": {
                "prompt_tokens": 7,
                "completion_tokens": 5,
                "total_tokens": 12,
            },
            "error_type": None,
            "api_key_name": None,
            "api_key_source": None,
        },
    )

    with pytest.raises(HTTPException) as ex:
        await verifier(request)

    assert ex.value.status_code == 429
    assert ex.value.headers["Retry-After"] == "55"
    assert "openai" in str(ex.value.detail)
