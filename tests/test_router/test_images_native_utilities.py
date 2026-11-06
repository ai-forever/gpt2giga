"""Real SDK boundaries for image generation and native utility endpoints."""

import base64
import json

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI
from test_sdk_alpha_boundaries import sdk_app

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig


def _image_response():
    return {
        "model": "test-model",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "files": [
                            {"id": "real-image", "mime": "image/png", "target": "image"}
                        ]
                    }
                ],
            }
        ],
    }


async def test_openai_sdk_generates_and_reads_real_image_bytes():
    seen = []
    image = b"\x89PNG\r\n\x00\xffimage"

    def handle(request):
        seen.append(request)
        if request.method == "POST":
            return httpx2.Response(200, json=_image_response())
        return httpx2.Response(200, content=image)

    async with sdk_app(handle) as (client, _):
        sdk = AsyncOpenAI(
            api_key="test", base_url="http://gateway.test/v2", http_client=client
        )
        response = await sdk.images.generate(
            model="gpt-image-1",
            prompt="A small lighthouse",
            n=1,
            response_format="b64_json",
        )
    assert base64.b64decode(response.data[0].b64_json) == image
    assert [request.url.path for request in seen] == [
        "/v2/chat/completions",
        "/v1/files/real-image/content",
    ]
    body = json.loads(seen[0].content)
    assert body["model"] == "test-model"
    assert body["tools"] == [{"image_generate": {}}]
    assert body["tool_config"]["mode"] == "any"
    assert seen[1].content == b""


@pytest.mark.parametrize(
    "payload",
    [
        {"n": 2},
        {"n": True},
        {"model": {"invalid": "shape"}},
        {"stream": True},
        {"size": "1024x1024"},
        {"response_format": "url"},
        {"quality": "high"},
        {"mask": "file"},
    ],
)
async def test_images_reject_unsupported_options_before_generation(payload):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx2.Response(200, json=_image_response())

    async with sdk_app(handle) as (client, _):
        response = await client.post(
            "/v2/images/generations", json={"prompt": "paint", **payload}
        )
    assert response.status_code == 400
    assert calls == []


@pytest.mark.parametrize("failure", ["timeout", "no_image", "empty_file"])
async def test_image_failures_never_repeat_generation(failure):
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("private upstream detail", request=request)
        if request.method == "GET":
            return httpx2.Response(200, content=b"")
        return httpx2.Response(
            200, json={"messages": []} if failure == "no_image" else _image_response()
        )

    async with sdk_app(handle) as (client, _):
        response = await client.post("/v2/images/generations", json={"prompt": "paint"})
    assert response.status_code == (504 if failure == "timeout" else 502)
    assert sum(request.method == "POST" for request in calls) == 1
    assert "private upstream detail" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "body", "native_path", "answer"),
    [
        (
            "POST",
            "tokens/count",
            {"input": ["hello"], "model": "test-model"},
            "/v1/tokens/count",
            [{"tokens": 1, "characters": 5, "object": "tokens"}],
        ),
        (
            "POST",
            "functions/validate",
            {"name": "lookup", "parameters": {"type": "object"}},
            "/v1/functions/validate",
            {"status": 200, "message": "OK"},
        ),
        (
            "GET",
            "balance",
            None,
            "/v1/balance",
            {"balance": [{"usage": "GigaChat", "value": 123.0}]},
        ),
        (
            "POST",
            "ai/check",
            {"input": "Русский текст", "model": "test-model"},
            "/v1/ai/check",
            {"category": "human", "characters": 13, "tokens": 4},
        ),
    ],
)
async def test_native_utility_sdk_method_and_safe_response(
    method, path, body, native_path, answer
):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx2.Response(
            200,
            json=answer,
            headers={"x-request-id": "upstream-safe", "set-cookie": "private"},
        )

    async with sdk_app(handle) as (client, _):
        response = await client.request(
            method,
            f"/bridge/gigachat/{path}",
            json=body,
            headers={"X-Session-ID": "utility-session"},
        )
    assert response.status_code == 200, response.text
    assert response.json() == answer
    assert len(seen) == 1
    assert seen[0].method == method
    assert seen[0].url.path == native_path
    assert seen[0].headers["x-session-id"] == "utility-session"
    if body is not None:
        assert json.loads(seen[0].content) == body
    assert "synthetic-token" not in response.text
    assert "private" not in response.text


async def test_native_surface_requires_configured_gateway_auth():
    app = create_app(
        ProxyConfig(proxy={"enable_api_key_auth": True, "api_key": "gateway-secret"})
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://gateway.test"
    ) as client:
        response = await client.get("/bridge/gigachat/balance")
    assert response.status_code == 401


async def test_native_operation_uses_pass_token_request_identity(monkeypatch):
    from gigachat import GigaChat
    from gpt2giga.middlewares.pass_token import PassTokenMiddleware

    seen = []

    def handle(request):
        seen.append(request)
        return httpx2.Response(200, json={"balance": []})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as wire:
        scoped = GigaChat(
            base_url="https://gigachat.test/v1",
            access_token="request-identity",
            credentials="",
            user="",
            password="",
            scope="",
            trust_env=False,
            async_http_client=wire,
            max_retries=0,
        )
        monkeypatch.setattr(
            "gpt2giga.middlewares.pass_token.create_gigachat_client_for_request",
            lambda settings, token: scoped,
        )
        async with sdk_app(handle) as (client, app):
            app.state.config.proxy_settings.pass_token = True
            app.add_middleware(PassTokenMiddleware)
            response = await client.get(
                "/bridge/gigachat/balance",
                headers={"Authorization": "Bearer request-identity"},
            )
    assert response.status_code == 200
    assert seen[0].headers["authorization"] == "Bearer request-identity"
    assert "request-identity" not in response.text


def test_new_routes_are_present_in_openapi():
    paths = create_app(ProxyConfig()).openapi()["paths"]
    for prefix in ("", "/v1", "/v2"):
        assert "post" in paths[f"{prefix}/images/generations"]
    for method, operation in (
        ("get", "balance"),
        ("post", "tokens/count"),
        ("post", "functions/validate"),
        ("post", "ai/check"),
    ):
        assert method in paths[f"/bridge/gigachat/{operation}"]
