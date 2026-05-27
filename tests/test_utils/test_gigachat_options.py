import json
from types import SimpleNamespace

import httpx
import pytest
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


def test_extract_gigachat_request_options_merges_sources_and_sanitizes():
    request = _make_request(
        headers={
            "Authorization": "Bearer proxy-token",
            "Content-Type": "application/json",
            "X-Me": "from-header",
            "X-Stainless-Lang": "python",
        },
        query_string=b"beta=true&x-api-key=secret&local=skip",
    )
    data = {
        "extra_headers": {
            "X-Me": "from-body",
            "X-Body": 123,
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

    assert options.headers == {"x-me": "from-body", "x-body": "123"}
    assert options.query == (
        ("beta", "true"),
        ("feature", "a"),
        ("feature", "b"),
        ("enabled", "true"),
    )
    assert options.body == {"profanity_check": False}
    assert data == {}


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
