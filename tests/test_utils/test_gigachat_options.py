import asyncio
import json
from types import SimpleNamespace

import httpx2 as httpx
from gigachat import GigaChat
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
        query_string=b"beta=true&x-api-key=secret&key=google-secret&local=skip",
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


async def test_gigachat_request_options_reset_after_exception():
    options = GigaRequestOptions(
        headers={"x-request-id": "request-before-error"}, query=(), body={}
    )

    with pytest.raises(RuntimeError, match="request failed"):
        async with gigachat_request_options(SimpleNamespace(), options):
            assert build_headers()["X-Request-ID"] == "request-before-error"
            raise RuntimeError("request failed")

    assert "X-Request-ID" not in build_headers()


@pytest.mark.parametrize("include_body", [True, False])
async def test_public_sdk_options_wire_and_owner_isolation(include_body):
    captured = []

    async def handler(request):
        captured.append(
            (
                tuple(request.url.params.multi_items()),
                json.loads(await request.aread()),
                dict(request.headers),
            )
        )
        return httpx.Response(
            200, json=[{"tokens": 1, "characters": 1, "object": "tokens"}]
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as http:
        owner = GigaChat(
            base_url="https://gigachat.test/api/v1",
            access_token="tenant",
            async_http_client=http,
            trust_env=False,
        )

        async def send(name):
            options = GigaRequestOptions(
                headers={"x-request-id": name},
                query=(("task", name), ("task", "repeated")),
                body={"task": name},
            )
            async with gigachat_request_options(
                owner, options, include_body=include_body
            ) as client:
                await asyncio.sleep(0)
                await client.atokens_count([name], model="GigaChat")

        await asyncio.gather(send("A"), send("B"))
        await owner.atokens_count(["owner"], model="GigaChat")
        await owner.aclose()
        assert not http.is_closed
    for query, body, headers in captured[:2]:
        name = body["input"][0]
        assert query == (("task", name), ("task", "repeated"))
        assert body.get("task") == (name if include_body else None)
        assert headers["x-request-id"] == name
    assert captured[2][0] == ()
    assert "task" not in captured[2][1]
    assert "x-request-id" not in captured[2][2]


async def test_header_only_yields_owner():
    owner = SimpleNamespace()
    async with gigachat_request_options(
        owner, GigaRequestOptions(headers={"x-request-id": "same"}, query=(), body={})
    ) as scoped:
        assert scoped is owner


async def test_stream_body_rejected_before_dispatch():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as http:
        owner = GigaChat(
            base_url="https://gigachat.test",
            access_token="tenant",
            async_http_client=http,
            trust_env=False,
        )
        with pytest.raises(ValueError):
            async with gigachat_request_options(
                owner, GigaRequestOptions(headers={}, query=(), body={"stream": True})
            ) as scoped:
                await scoped.achat(
                    {
                        "model": "GigaChat",
                        "messages": [{"role": "user", "content": "hello"}],
                    }
                )
        assert calls == []
        await owner.aclose()
