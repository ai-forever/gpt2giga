"""Mounted text-only additions and explicit Anthropic version policy."""

import json

import httpx2
import pytest

from test_sdk_alpha_boundaries import sdk_app


@pytest.mark.parametrize("prefix", ["", "/v1", "/v2"])
async def test_response_input_tokens_counts_text_schemas_without_chat(prefix):
    seen = []

    def handle(request):
        seen.append(request)
        assert request.url.path.endswith("/tokens/count")
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        text = " ".join(payload["input"])
        for value in ["instructions", "hello", "lookup", "city", "answer"]:
            assert value in text
        return httpx2.Response(
            200,
            json=[
                {"tokens": 3, "characters": 10, "object": "tokens"}
                for _ in payload["input"]
            ],
        )

    async with sdk_app(handle) as (client, _):
        response = await client.post(
            f"{prefix}/responses/input_tokens",
            json={
                "model": "test-model",
                "instructions": "instructions",
                "input": "hello",
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        },
                    }
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "result",
                        "schema": {
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                        },
                    }
                },
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["object"] == "response.input_tokens"
    assert response.json()["input_tokens"] > 0
    assert len(seen) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"previous_response_id": "resp_x"},
        {"conversation": "conv_x"},
        {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "https://example.com/image.png",
                        }
                    ],
                }
            ]
        },
        {"tools": [{"type": "web_search"}]},
    ],
)
async def test_response_input_tokens_rejects_nontext_without_dispatch(extra):
    def handle(request):
        pytest.fail("Unsupported estimates must not dispatch")

    async with sdk_app(handle) as (client, _):
        response = await client.post(
            "/v1/responses/input_tokens",
            json={"model": "test-model", "input": "hello", **extra},
        )
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("route", ["messages", "messages/count_tokens"])
@pytest.mark.parametrize("field", ["temperature", "top_p", "top_k", "document"])
async def test_anthropic_new_version_rejects_before_dispatch(route, field):
    def handle(request):
        pytest.fail("Version validation must precede dispatch")

    data = {
        "model": "test-model",
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "hello"}],
    }
    if field == "document":
        data["messages"] = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "document",
                        "source": {"type": "file", "file_id": "file-x"},
                    }
                ],
            }
        ]
    else:
        data[field] = 1
    async with sdk_app(handle) as (client, _):
        response = await client.post(
            f"/v1/{route}", headers={"anthropic-version": "2026-10-21"}, json=data
        )
    assert response.status_code == 400, response.text
    assert response.json()["type"] == "error"


async def test_openai_sdk_input_tokens_and_cache_identity():
    from openai import AsyncOpenAI

    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/tokens/count"):
            return httpx2.Response(
                200, json=[{"tokens": 7, "characters": 12, "object": "tokens"}]
            )
        return httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "created": 1,
                "model": "test-model",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            },
        )

    async with sdk_app(handle) as (http, app):
        sdk = AsyncOpenAI(
            api_key="test", base_url="http://gateway.test/v1", http_client=http
        )
        counted = await sdk.responses.input_tokens.count(
            model="test-model", input="hello"
        )
        assert counted.input_tokens == 7
        for model, key, headers in [
            ("test-model", "secret-key", {}),
            ("test-model", "secret-key", {}),
            ("other-model", "secret-key", {}),
            ("test-model", "other-key", {}),
            ("test-model", "secret-key", {"X-Session-ID": "explicit-session"}),
        ]:
            await sdk.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hello"}],
                prompt_cache_key=key,
                extra_headers=headers,
            )
        sessions = [request.headers.get("x-session-id") for request in seen[1:]]
        assert sessions[0] == sessions[1]
        assert len(set(sessions[:4])) == 3
        assert sessions[4] == "explicit-session"
        assert all("secret-key" not in value for value in sessions)


async def test_response_count_includes_replayed_reasoning_text():
    seen = []

    def handle(request):
        seen.append(request)
        assert request.url.path.endswith("/tokens/count")
        payload = json.loads(request.content)
        assert "Visible reasoning summary" in payload["input"]
        return httpx2.Response(
            200,
            json=[
                {"tokens": 1, "characters": len(text), "object": "tokens"}
                for text in payload["input"]
            ],
        )

    async with sdk_app(handle) as (client, _):
        response = await client.post(
            "/v1/responses/input_tokens",
            json={
                "model": "test-model",
                "input": [
                    {
                        "type": "reasoning",
                        "id": "rs_test",
                        "summary": [
                            {
                                "type": "summary_text",
                                "text": "Visible reasoning summary",
                            }
                        ],
                    },
                    {
                        "type": "function_call",
                        "id": "fc_test",
                        "call_id": "call_test",
                        "name": "lookup",
                        "arguments": "{}",
                    },
                ],
            },
        )
        assert response.status_code == 200, response.text
    assert len(seen) == 1


async def test_explicit_cache_key_separates_selected_profiles():
    from starlette.requests import Request
    from gpt2giga.common.cache_session import apply_cache_session_id
    from gpt2giga.core.context import build_request_context, request_context_var
    from gpt2giga.providers.gigachat.request_options import GigaRequestOptions

    async with sdk_app(lambda _: pytest.fail("No network for cache key")) as (_, app):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/responses",
                "headers": [],
                "app": app,
                "server": ("gateway.test", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )
        request.state.prompt_cache_key = "same-key"
        context = build_request_context(request, request_id="test-cache")
        token = request_context_var.set(context)
        try:
            values = []
            for profile in ("profile-a", "profile-b", "profile-a"):
                context.profile_id = profile
                options = apply_cache_session_id(
                    request,
                    {},
                    GigaRequestOptions(headers={}, query=(), body={}),
                    model="same-model",
                )
                values.append(options.headers["x-session-id"])
            assert values[0] == values[2]
            assert values[0] != values[1]
            assert all("same-key" not in value for value in values)
        finally:
            request_context_var.reset(token)


async def test_input_tokens_unknown_alias_and_nontext_have_openai_error_envelope():
    from types import SimpleNamespace
    from gpt2giga.providers.profiles import ProviderAliasError

    class StaticRegistry:
        config = SimpleNamespace(profiles=())

        def resolve(self, model):
            raise ProviderAliasError("not_configured")

    async with sdk_app(
        lambda _: pytest.fail("Invalid estimates must not dispatch")
    ) as (client, app):
        response = await client.post(
            "/responses/input_tokens",
            json={
                "model": "test-model",
                "input": "hello",
                "previous_response_id": "resp_missing",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["param"] == "previous_response_id"
        assert "detail" not in response.json()
        app.state.provider_registry = StaticRegistry()
        response = await client.post(
            "/responses/input_tokens", json={"model": "unknown", "input": "hello"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "unknown_model_alias"
