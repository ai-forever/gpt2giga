import json
from types import SimpleNamespace

import httpx
import pytest
from gigachat.api.utils import build_headers
from starlette.requests import Request

from gpt2giga.common.gigachat_options import (
    GigaRequestOptions,
    extract_gigachat_request_options,
    gigachat_request_options,
)


def _make_request(headers=None, query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat/completions",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in (headers or {}).items()
            ],
            "query_string": query_string,
        }
    )


def test_extract_gigachat_request_options_allows_only_safe_metadata():
    request = _make_request(
        headers={
            "Authorization": "Bearer proxy-token",
            "Content-Type": "application/json",
            "X-Request-ID": "from-header",
            "X-Stainless-Lang": "python",
        },
        query_string=b"beta=true&x-api-key=secret&local=skip",
    )
    data = {
        "extra_headers": {
            "X-Request-ID": "from-body",
            "X-Session-ID": "sdk-session",
            "X-Correlation-ID": 123,
            "X-Body": "from-extra-headers",
            "Authorization": "Bearer bad",
        },
        "extra_query": {"feature": ["a", "b"], "enabled": True},
        "extra_body": {"profanity_check": False},
    }

    options = extract_gigachat_request_options(
        request,
        data,
        include_extra_body=True,
        exclude_query_params=("local",),
    )

    assert options.headers == {
        "x-request-id": "from-body",
        "x-session-id": "sdk-session",
        "x-correlation-id": "123",
        "x-body": "from-extra-headers",
    }
    assert options.query == ()
    assert options.body == {"profanity_check": False}
    assert data == {}


def test_extract_gigachat_request_options_drops_provider_sdk_metadata():
    request = _make_request(
        headers={
            "X-Foo": "from-header",
            "Anthropic-Beta": "tools-2026-01-01",
            "OpenAI-Organization": "org_test",
        },
        query_string=b"unknown=1&feature=on",
    )

    options = extract_gigachat_request_options(
        request,
        {
            "extra_headers": {"X-Bar": "from-extra-headers"},
            "extra_query": {"extra": "from-extra-query"},
        },
    )

    assert options.headers == {
        "x-foo": "from-header",
        "x-bar": "from-extra-headers",
    }
    assert options.query == ()


@pytest.mark.asyncio
async def test_gigachat_request_options_sets_gigachat_header_contextvars():
    options = GigaRequestOptions(
        headers={
            "Authorization": "Bearer jwe",
            "x-request-id": "rq-1",
            "x-session-id": "session-1",
            "x-client-id": "client-1",
            "x-service-id": "service-1",
            "x-operation-id": "operation-1",
            "x-trace-id": "trace-1",
            "x-agent-id": "agent-1",
            "x-custom": "custom-1",
        },
        query=(),
        body={},
    )

    async with gigachat_request_options(SimpleNamespace(), options):
        headers = build_headers()

    assert headers["Authorization"] == "Bearer jwe"
    assert headers["X-Request-ID"] == "rq-1"
    assert headers["X-Session-ID"] == "session-1"
    assert headers["X-Client-ID"] == "client-1"
    assert headers["X-Service-ID"] == "service-1"
    assert headers["X-Operation-ID"] == "operation-1"
    assert headers["X-Trace-ID"] == "trace-1"
    assert headers["X-Agent-ID"] == "agent-1"
    assert headers["x-custom"] == "custom-1"

    headers_after_context = build_headers()
    assert headers_after_context == {"User-Agent": "GigaChat-python-lib"}


@pytest.mark.asyncio
async def test_gigachat_request_options_hook_applies_headers_query_and_body():
    captured = {}

    async def handler(request):
        captured["headers"] = dict(request.headers)
        captured["query"] = tuple(request.url.params.multi_items())
        captured["body"] = json.loads(await request.aread())
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://gigachat.test", transport=transport
    ) as client:
        giga_client = SimpleNamespace(_aclient=client)
        options = GigaRequestOptions(
            headers={"X-Me": "kus"},
            query=(("beta", "true"),),
            body={"profanity_check": False},
        )
        async with gigachat_request_options(giga_client, options):
            response = await client.post(
                "/chat/completions?existing=1",
                json={"model": "GigaChat", "messages": []},
            )

    assert response.status_code == 200
    assert captured["headers"]["x-me"] == "kus"
    assert captured["query"] == (("existing", "1"), ("beta", "true"))
    assert captured["body"] == {
        "model": "GigaChat",
        "messages": [],
        "profanity_check": False,
    }


@pytest.mark.asyncio
async def test_gigachat_request_options_hook_skips_auth_requests():
    captured = {}

    async def handler(request):
        captured["headers"] = dict(request.headers)
        captured["query"] = tuple(request.url.params.multi_items())
        captured["body"] = await request.aread()
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://gigachat.test", transport=transport
    ) as client:
        giga_client = SimpleNamespace(_aclient=client)
        options = GigaRequestOptions(
            headers={"X-Me": "kus"},
            query=(("beta", "true"),),
            body={"profanity_check": False},
        )
        async with gigachat_request_options(giga_client, options):
            response = await client.post("/oauth", json={"scope": "GIGACHAT_API_PERS"})

    assert response.status_code == 200
    assert "x-me" not in captured["headers"]
    assert captured["query"] == ()
    assert json.loads(captured["body"]) == {"scope": "GIGACHAT_API_PERS"}
