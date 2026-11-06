"""Request-scoped header, query, and body isolation contracts."""

from __future__ import annotations

import asyncio
import json
from gigachat import GigaChat

import httpx2 as httpx
import pytest
from gigachat.api.utils import build_headers

from gpt2giga.common.gigachat_options import (
    GigaRequestOptions,
    gigachat_request_options,
)


async def test_sdk_context_headers_query_and_body_reach_mock_transport() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["query"] = tuple(request.url.params.multi_items())
        captured["body"] = json.loads(await request.aread())
        return httpx.Response(
            200, json=[{"tokens": 1, "characters": 1, "object": "tokens"}]
        )

    async with httpx.AsyncClient(
        base_url="https://gigachat.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        sdk_client = GigaChat(
            base_url="https://gigachat.test",
            access_token="tenant",
            async_http_client=client,
            trust_env=False,
        )
        options = GigaRequestOptions(
            headers={
                "authorization": "Bearer request-token",
                "x-request-id": "request-1",
                "x-session-id": "session-1",
                "x-client-id": "client-1",
                "x-service-id": "service-1",
                "x-operation-id": "operation-1",
                "x-trace-id": "trace-1",
                "x-agent-id": "agent-1",
                "x-contract-header": "custom-1",
            },
            query=(("feature", "one"), ("feature", "two")),
            body={"profanity_check": False, "contract_flag": "on"},
        )
        async with gigachat_request_options(sdk_client, options) as scoped:
            await scoped.atokens_count([], model="GigaChat")
        await sdk_client.aclose()

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer request-token"
    assert headers["x-request-id"] == "request-1"
    assert headers["x-session-id"] == "session-1"
    assert headers["x-client-id"] == "client-1"
    assert headers["x-service-id"] == "service-1"
    assert headers["x-operation-id"] == "operation-1"
    assert headers["x-trace-id"] == "trace-1"
    assert headers["x-agent-id"] == "agent-1"
    assert headers["x-contract-header"] == "custom-1"
    assert captured["query"] == (
        ("feature", "one"),
        ("feature", "two"),
    )
    assert captured["body"] == {
        "model": "GigaChat",
        "input": [],
        "profanity_check": False,
        "contract_flag": "on",
    }
    assert build_headers() == {"User-Agent": "GigaChat-python-lib"}


@pytest.mark.parametrize("auth_path", ["/oauth", "/token", "/oauth/session"])
async def test_transport_options_are_excluded_from_oauth_requests(auth_path):
    captured = []

    async def handler(request):
        captured.append(request)
        if request.url.path == auth_path:
            return httpx.Response(
                200, json={"access_token": "tenant", "expires_at": 9999999999999}
            )
        return httpx.Response(
            200, json=[{"tokens": 1, "characters": 1, "object": "tokens"}]
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as http:
        owner = GigaChat(
            base_url="https://gigachat.test",
            auth_url="https://auth.test" + auth_path,
            credentials="tenant-credentials",
            async_http_client=http,
            auth_async_http_client=http,
            trust_env=False,
        )
        options = GigaRequestOptions(
            headers={},
            query=(("feature", "must-not-leak"),),
            body={"contract_flag": "must-not-leak"},
        )
        async with gigachat_request_options(owner, options) as scoped:
            await scoped.atokens_count(["hello"], model="GigaChat")
        await owner.aclose()
    oauth = captured[0]
    assert oauth.url.path == auth_path
    assert not oauth.url.query
    assert b"must-not-leak" not in oauth.content
    assert oauth.content == b"scope=GIGACHAT_API_PERS"


async def test_concurrent_contextvars_do_not_cross_contaminate_requests() -> None:
    captured: dict[str, tuple[str | None, tuple, dict]] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        captured[json.loads(await request.aread())["input"][0]] = (
            request.headers.get("x-request-id"),
            tuple(request.url.params.multi_items()),
            json.loads(await request.aread()),
        )
        return httpx.Response(
            200, json=[{"tokens": 1, "characters": 1, "object": "tokens"}]
        )

    async with httpx.AsyncClient(
        base_url="https://gigachat.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        sdk_client = GigaChat(
            base_url="https://gigachat.test",
            access_token="tenant",
            async_http_client=client,
            trust_env=False,
        )

        async def send(name: str) -> None:
            options = GigaRequestOptions(
                headers={"x-request-id": f"request-{name}"},
                query=(("task", name),),
                body={"task": name},
            )
            async with gigachat_request_options(sdk_client, options) as scoped:
                await asyncio.sleep(0)
                await scoped.atokens_count([name], model="GigaChat")

        await asyncio.gather(send("first"), send("second"))
        await sdk_client.aclose()

    assert captured["first"] == (
        "request-first",
        (("task", "first"),),
        {"model": "GigaChat", "input": ["first"], "task": "first"},
    )
    assert captured["second"] == (
        "request-second",
        (("task", "second"),),
        {"model": "GigaChat", "input": ["second"], "task": "second"},
    )
    assert build_headers() == {"User-Agent": "GigaChat-python-lib"}
