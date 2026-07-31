"""Request-scoped header, query, and body isolation contracts."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
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
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        base_url="https://gigachat.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        sdk_client = SimpleNamespace(_aclient=client)
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
        async with gigachat_request_options(sdk_client, options):
            await client.post(
                "/chat/completions?existing=1",
                headers=build_headers(),
                json={"model": "GigaChat", "messages": []},
            )

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
        ("existing", "1"),
        ("feature", "one"),
        ("feature", "two"),
    )
    assert captured["body"] == {
        "model": "GigaChat",
        "messages": [],
        "profanity_check": False,
        "contract_flag": "on",
    }
    assert build_headers() == {"User-Agent": "GigaChat-python-lib"}


@pytest.mark.parametrize("auth_path", ["/oauth", "/token", "/oauth/session"])
async def test_transport_options_are_excluded_from_oauth_requests(
    auth_path: str,
) -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = tuple(request.url.params.multi_items())
        captured["body"] = json.loads(await request.aread())
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        base_url="https://gigachat.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        options = GigaRequestOptions(
            headers={},
            query=(("feature", "must-not-leak"),),
            body={"contract_flag": "must-not-leak"},
        )
        async with gigachat_request_options(SimpleNamespace(_aclient=client), options):
            await client.post(auth_path, json={"scope": "GIGACHAT_API_PERS"})

    assert captured["query"] == ()
    assert captured["body"] == {"scope": "GIGACHAT_API_PERS"}


async def test_concurrent_contextvars_do_not_cross_contaminate_requests() -> None:
    captured: dict[str, tuple[str | None, tuple, dict]] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        captured[request.url.path] = (
            request.headers.get("x-request-id"),
            tuple(request.url.params.multi_items()),
            json.loads(await request.aread()),
        )
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        base_url="https://gigachat.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        sdk_client = SimpleNamespace(_aclient=client)

        async def send(name: str) -> None:
            options = GigaRequestOptions(
                headers={"x-request-id": f"request-{name}"},
                query=(("task", name),),
                body={"task": name},
            )
            async with gigachat_request_options(sdk_client, options):
                await asyncio.sleep(0)
                await client.post(
                    f"/{name}",
                    headers=build_headers(),
                    json={"base": name},
                )

        await asyncio.gather(send("first"), send("second"))

    assert captured["/first"] == (
        "request-first",
        (("task", "first"),),
        {"base": "first", "task": "first"},
    )
    assert captured["/second"] == (
        "request-second",
        (("task", "second"),),
        {"base": "second", "task": "second"},
    )
    assert build_headers() == {"User-Agent": "GigaChat-python-lib"}
