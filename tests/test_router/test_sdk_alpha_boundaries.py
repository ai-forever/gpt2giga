"""Real alpha SDK boundaries through the mounted application, without sockets."""

import json
import tempfile
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest
from gigachat import GigaChat
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.storage.resources import ResourceStore


@asynccontextmanager
async def sdk_app(handler, *, normalization="on", fallback=True, auth=False):
    config = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            pass_model=True,
            normalization_mode=normalization,
            legacy_chat_fallback=fallback,
            enable_api_key_auth=auth,
            api_key="synthetic-gateway-key",
        ),
        gigachat={"model": "test-model", "max_retries": 0},
    )
    app = create_app(config)
    app.state.logger = logger
    temporary_store = tempfile.TemporaryDirectory()
    app.state.resource_store = await ResourceStore.open(temporary_store.name)
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), trust_env=False
    ) as wire:
        sdk = GigaChat(
            base_url="https://gigachat.test/v1",
            access_token="synthetic-token",
            credentials="",
            user="",
            password="",
            scope="",
            max_retries=0,
            async_http_client=wire,
            trust_env=False,
        )
        app.state.gigachat_client = sdk
        app.state.request_transformer = RequestTransformer(config, logger=logger)
        app.state.response_processor = ResponseProcessor(logger=logger)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway.test"
        ) as client:
            yield client, app
        await sdk.aclose()
        assert not wire.is_closed  # The fixture owns the injected HTTP client.
    await app.state.resource_store.aclose()
    temporary_store.cleanup()


@pytest.mark.parametrize("prefix", ["", "/v1", "/v2"])
@pytest.mark.parametrize("content", [b"", b"\x00\xff\x80binary\r\n"])
async def test_mounted_files_preserve_sdk_bytes(prefix, content):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx2.Response(200, content=content)

    async with sdk_app(handle) as (client, _):
        response = await client.get(f"{prefix}/files/synthetic-file/content")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content == content
    assert len(seen) == 1
    assert seen[0].url.path.endswith("/files/synthetic-file/content")


def chat_request(protocol, mode, *, stream=False):
    if protocol == "responses":
        return f"/{mode}/responses", {
            "model": "test-model",
            "input": "hello",
            "stream": stream,
        }
    if protocol == "gemini":
        method = "streamGenerateContent" if stream else "generateContent"
        return f"/{mode}/v1beta/models/test-model:{method}", {
            "contents": [{"role": "user", "parts": [{"text": "hello"}]}]
        }
    data = {
        "model": "test-model",
        "stream": stream,
        "messages": [{"role": "user", "content": "hello"}],
    }
    if protocol == "anthropic":
        data["max_tokens"] = 32
    return (
        f"/{mode}/{'messages' if protocol == 'anthropic' else 'chat/completions'}",
        data,
    )


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "gemini"])
@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("failure", ["timeout", "connection", "invalid_json"])
async def test_dispatch_failure_has_one_post_and_safe_protocol_error(
    protocol, mode, fallback, failure
):
    seen = []

    def handle(request):
        seen.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("synthetic-secret-body", request=request)
        if failure == "connection":
            raise httpx2.ConnectError("synthetic-secret-body", request=request)
        return httpx2.Response(
            200,
            content=b"synthetic-secret-body",
            headers={"x-request-id": "upstream-test-id"},
        )

    async with sdk_app(handle, fallback=fallback) as (client, _):
        path, data = chat_request(protocol, mode)
        response = await client.post(path, json=data)
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == f"/{mode}/chat/completions"
    assert response.status_code == (504 if failure == "timeout" else 502), response.text
    error = response.json()["error"]
    if protocol == "gemini":
        assert error["status"] == (
            "DEADLINE_EXCEEDED" if failure == "timeout" else "UNAVAILABLE"
        )
    else:
        assert (
            error["code"]
            == {
                "timeout": "upstream_timeout",
                "connection": "upstream_connection_error",
                "invalid_json": "invalid_upstream_response",
            }[failure]
        )
        if protocol == "anthropic":
            assert response.json()["type"] == "error"
            assert error["type"] == "api_error"
    assert "synthetic-secret" not in response.text
    assert response.headers["x-request-id"] != "upstream-test-id"
    if failure == "invalid_json":
        assert response.headers["x-gigachat-request-id"] == "upstream-test-id"


class IncompleteStream(httpx2.AsyncByteStream):
    def __init__(self, mode, finish_before_error=False):
        self.mode = mode
        self.finish_before_error = finish_before_error
        self.closed = False

    async def __aiter__(self):
        if self.mode == "v1":
            chunk = {
                "choices": [
                    {"delta": {"role": "assistant", "content": "hello"}, "index": 0}
                ]
            }
        else:
            chunk = {
                "messages": [{"role": "assistant", "content": [{"text": "hello"}]}]
            }
        chunk.update(created=1, model="test-model", object="chat.completion.chunk")
        if self.mode == "v1":
            chunk["choices"][0]["finish_reason"] = (
                "stop" if self.finish_before_error else None
            )
        elif self.finish_before_error:
            chunk["finish_reason"] = "stop"
        yield f"data: {json.dumps(chunk)}\n\n".encode()
        if self.mode == "v1":
            raise httpx2.ReadError("synthetic-secret-body")
        # v2 EOF is deliberately missing the required terminal event.

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "gemini", "responses"])
@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("normalization", ["off", "on"])
@pytest.mark.parametrize("finish_before_error", [False, True])
async def test_sdk_interruption_is_safe_sse_error_with_request_id(
    protocol, mode, normalization, finish_before_error
):
    wire_stream = IncompleteStream(mode, finish_before_error)
    seen = []

    def handle(request):
        seen.append(request)
        return httpx2.Response(
            200,
            stream=wire_stream,
            headers={
                "content-type": "text/event-stream",
                "x-request-id": "upstream-stream-id",
            },
        )

    async with sdk_app(handle, normalization=normalization) as (client, _):
        path, data = chat_request(protocol, mode, stream=True)
        response = await client.post(path, json=data)
    assert response.status_code == 200, response.text
    frames = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    errors = [frame["error"] for frame in frames if "error" in frame]
    if protocol == "responses":
        errors = [frame for frame in frames if frame.get("type") == "error"]
    assert len(errors) == 1, response.text
    assert errors[0]["code"] == (502 if protocol == "gemini" else "stream_interrupted")
    assert errors[0]["metadata"] == {"gigachat_x_request_id": "upstream-stream-id"}
    assert all(
        not choice.get("finish_reason")
        for frame in frames
        for choice in frame.get("choices", [])
    )
    assert all(
        not candidate.get("finishReason")
        for frame in frames
        for candidate in frame.get("candidates", [])
    )
    assert "response.completed" not in response.text
    assert "message_stop" not in response.text
    assert len(seen) == 1
    assert wire_stream.closed


@pytest.mark.parametrize("request_id", [None, "synthetic-upstream-id"])
def test_sse_error_serializers_select_only_upstream_request_id(request_id):
    from gpt2giga.protocols.normalized import NormalizedError, NormalizedStreamEvent
    from gpt2giga.protocols.openai.streaming import (
        normalized_stream_event_to_openai_chunk,
    )
    from gpt2giga.protocols.openai.responses_streaming import ResponsesStreamProjector
    from gpt2giga.protocols.anthropic.streaming import AnthropicStreamProjector
    from gpt2giga.protocols.gemini.streaming import (
        normalized_stream_event_to_gemini_chunk,
    )

    event = NormalizedStreamEvent(
        type="error",
        error=NormalizedError(
            type="api_error",
            message="The upstream response was invalid.",
            code="invalid_upstream_response",
            provider_metadata={
                "gigachat": {
                    "request_id": request_id,
                    "body": "synthetic-secret",
                    "headers": {"authorization": "synthetic-secret"},
                },
                "other": "synthetic-secret",
            },
        ),
    )
    kwargs = {"requested_model": "test", "response_id": "test"}
    errors = [
        normalized_stream_event_to_openai_chunk(event, **kwargs)["error"],
        normalized_stream_event_to_gemini_chunk(event, **kwargs)["error"],
    ]
    anthropic = AnthropicStreamProjector(**kwargs)
    responses = ResponsesStreamProjector(request_payload={}, created_at=1, **kwargs)
    errors.append(json.loads(anthropic.project(event)[0].splitlines()[1][6:])["error"])
    responses.project(NormalizedStreamEvent(type="message_start", sequence=0))
    errors.append(
        json.loads(
            responses.project(event.model_copy(update={"sequence": 1}))[0].splitlines()[
                1
            ][6:]
        )
    )
    for error in errors:
        assert "synthetic-secret" not in json.dumps(error)
        if request_id:
            assert error["metadata"] == {"gigachat_x_request_id": request_id}
        else:
            assert "metadata" not in error


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "gemini"])
async def test_tool_finish_without_sdk_terminal_does_not_report_success(protocol):
    class ToolStream(IncompleteStream):
        async def __aiter__(self):
            chunk = {
                "messages": [
                    {
                        "role": "assistant",
                        "tools_state_id": "synthetic-state",
                        "content": [
                            {
                                "function_call": {
                                    "id": "call-a",
                                    "name": "lookup",
                                    "arguments": {},
                                }
                            }
                        ],
                    }
                ],
                "finish_reason": "function_call",
            }
            yield f"data: {json.dumps(chunk)}\n\n".encode()

    stream = ToolStream("v2")
    async with sdk_app(
        lambda _: httpx2.Response(
            200, stream=stream, headers={"content-type": "text/event-stream"}
        )
    ) as (client, _):
        path, data = chat_request(protocol, "v2", stream=True)
        response = await client.post(path, json=data)
    assert response.status_code == 200
    assert (
        '"code": 502' if protocol == "gemini" else "stream_interrupted"
    ) in response.text
    assert '"finish_reason": "tool_calls"' not in response.text
    assert '"finish_reason": "function_call"' not in response.text
    assert "finishReason" not in response.text
    assert "message_stop" not in response.text
    assert stream.closed


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("failure", ["timeout", "connection", "invalid_json"])
async def test_gemini_count_tokens_never_replays_after_dispatch(fallback, failure):
    seen = []

    def handle(request):
        seen.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("synthetic-secret", request=request)
        if failure == "connection":
            raise httpx2.ConnectError("synthetic-secret", request=request)
        return httpx2.Response(200, content=b"synthetic-secret")

    async with sdk_app(handle, fallback=fallback) as (client, _):
        response = await client.post(
            "/v1/models/test-model:countTokens",
            json={"contents": [{"parts": [{"text": "hello"}]}]},
        )
    assert len(seen) == 1
    assert seen[0].url.path == "/v1/tokens/count"
    assert response.status_code == (504 if failure == "timeout" else 502)
    assert response.json()["error"]["code"] == response.status_code
    assert "synthetic-secret" not in response.text


@pytest.mark.parametrize(
    "prefix", ["", "/v1", "/v2", "/v1beta", "/v1/v1beta", "/v2/v1beta"]
)
@pytest.mark.parametrize("failure", ["timeout", "status", "invalid_request"])
async def test_gemini_aliases_share_google_errors(prefix, failure):
    seen = []

    def handle(request):
        seen.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("synthetic-secret", request=request)
        return httpx2.Response(
            429,
            json={"message": "synthetic-secret"},
            headers={"x-request-id": "upstream-rate-limit"},
        )

    async with sdk_app(handle) as (client, _):
        operation = (
            "batchEmbedContents" if failure == "invalid_request" else "generateContent"
        )
        response = await client.post(
            f"{prefix}/models/test-model:{operation}",
            json={"requests": []}
            if failure == "invalid_request"
            else {"contents": [{"parts": [{"text": "hello"}]}]},
        )
    status, canonical = {
        "timeout": (504, "DEADLINE_EXCEEDED"),
        "status": (429, "RESOURCE_EXHAUSTED"),
        "invalid_request": (400, "INVALID_ARGUMENT"),
    }[failure]
    assert response.status_code == status
    assert response.json()["error"]["code"] == status
    assert response.json()["error"]["status"] == canonical
    assert "detail" not in response.json()
    assert "synthetic-secret" not in response.text
    assert len(seen) == (0 if failure == "invalid_request" else 1)
    if failure == "status":
        assert response.headers["x-gigachat-request-id"] == "upstream-rate-limit"
        assert response.headers["x-request-id"] != "upstream-rate-limit"


@pytest.mark.parametrize(
    "rows",
    [
        [{"embedding": [1.0], "index": 0}],
        [{"embedding": [1.0], "index": n} for n in range(3)],
        [{"embedding": [1.0], "index": 0}, {"embedding": [2.0], "index": 0}],
        [{"embedding": [1.0], "index": 0}, {"embedding": [2.0], "index": 2}],
        [{"embedding": [1.0], "index": 0}, {"embedding": [], "index": 1}],
        [{"embedding": [1.0], "index": 0}, {"index": 1}],
    ],
)
async def test_malformed_embedding_response_is_upstream_error(rows):
    rows = [
        {"usage": {"prompt_tokens": 1}, "object": "embedding", **row} for row in rows
    ]
    async with sdk_app(
        lambda _: httpx2.Response(
            200, json={"data": rows, "model": "test-model", "object": "list"}
        )
    ) as (client, _):
        response = await client.post(
            "/models/test-model:batchEmbedContents",
            json={
                "requests": [
                    {"content": {"parts": [{"text": text}]}}
                    for text in ("first", "second")
                ]
            },
        )
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == 502


async def test_reordered_embeddings_restore_input_order():
    rows = [{"embedding": [2.0], "index": 1}, {"embedding": [1.0], "index": 0}]
    rows = [
        {"usage": {"prompt_tokens": 1}, "object": "embedding", **row} for row in rows
    ]
    async with sdk_app(
        lambda _: httpx2.Response(
            200, json={"data": rows, "model": "test-model", "object": "list"}
        )
    ) as (client, _):
        response = await client.post(
            "/models/test-model:batchEmbedContents",
            json={
                "requests": [
                    {"content": {"parts": [{"text": text}]}}
                    for text in ("first", "second")
                ]
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["embeddings"] == [{"values": [1.0]}, {"values": [2.0]}]


def test_gemini_sse_timeout_uses_google_status_and_safe_metadata():
    from gpt2giga.protocols.gemini.streaming import (
        normalized_stream_event_to_gemini_chunk,
    )
    from gpt2giga.protocols.normalized import NormalizedError, NormalizedStreamEvent

    event = NormalizedStreamEvent(
        type="error",
        error=NormalizedError(
            type="api_error",
            code="upstream_timeout",
            message="Request timed out.",
            provider_metadata={
                "gigachat": {"request_id": "upstream-timeout", "secret": "hidden"}
            },
        ),
    )
    result = normalized_stream_event_to_gemini_chunk(
        event, requested_model="test", response_id="gateway-id"
    )
    assert result == {
        "error": {
            "code": 504,
            "status": "DEADLINE_EXCEEDED",
            "message": "Request timed out.",
            "metadata": {"gigachat_x_request_id": "upstream-timeout"},
        }
    }


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("normalization", ["off", "on"])
async def test_reasoning_and_hosted_tool_survive_sdk_boundary(
    mode, normalization, monkeypatch
):
    import gpt2giga.providers.gigachat.adapter as provider_module

    monkeypatch.setattr(
        provider_module,
        "normalized_chat_to_openai_payload",
        lambda _: pytest.fail(
            "Execution must use typed SDK preparation, not the compatibility preview"
        ),
    )
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        if mode == "v1":
            result = {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "created": 1,
                "model": "test-model",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        else:
            result = {
                "messages": [{"role": "assistant", "content": [{"text": "ok"}]}],
                "finish_reason": "stop",
                "model": "test-model",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        return httpx2.Response(200, json=result)

    async with sdk_app(handle, normalization=normalization) as (client, _):
        path, data = chat_request("openai", mode)
        data["reasoning"] = {"effort": "high", "max_tokens": 64}
        if mode == "v2":
            data["tools"] = [{"type": "web_search"}]
        response = await client.post(path, json=data)
    assert response.status_code == 200, response.text
    assert len(seen) == 1
    if mode == "v1":
        assert seen[0]["reasoning_effort"] == "high"
        assert seen[0]["reasoning_max_tokens"] == 64
    else:
        assert seen[0]["model_options"]["reasoning"] == {
            "effort": "high",
            "max_tokens": 64,
        }
        assert seen[0]["tools"] == [{"web_search": {}}]


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("normalization", ["off", "on"])
@pytest.mark.parametrize(
    "content", ['<think>private plan</think>{"answer":1}', '{"answer":1}']
)
async def test_reasoning_content_is_decoded_before_projection(
    mode, normalization, content
):
    def handle(request):
        if mode == "v1":
            result = {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "created": 1,
                "model": "test-model",
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        else:
            result = {
                "messages": [{"role": "assistant", "content": [{"text": content}]}],
                "finish_reason": "stop",
                "model": "test-model",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        return httpx2.Response(200, json=result)

    async with sdk_app(handle, normalization=normalization) as (client, _):
        path, data = chat_request("openai", mode)
        response = await client.post(path, json=data)
    assert response.status_code == 200, response.text
    message = response.json()["choices"][0]["message"]
    assert json.loads(message["content"]) == {"answer": 1}
    assert message.get("reasoning_content") == (
        "private plan" if "<think>" in content else None
    )


@pytest.mark.parametrize("storage_mode", ["native", "gateway"])
@pytest.mark.parametrize("mode", ["v1", "v2"])
async def test_responses_done_without_semantic_finish_is_error(mode, storage_mode):
    chunk = (
        {
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "partial"}}
            ]
        }
        if mode == "v1"
        else {"messages": [{"role": "assistant", "content": [{"text": "partial"}]}]}
    )

    def handle(request):
        return httpx2.Response(
            200,
            text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    async with sdk_app(handle) as (client, app):
        app.state.config.proxy_settings.responses_storage_mode = storage_mode
        path, data = chat_request("responses", mode, stream=True)
        response = await client.post(path, json=data)
        frames = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        errors = [frame for frame in frames if frame.get("type") == "error"]
        assert len(errors) == 1, response.text
        assert not any(
            frame.get("type") in {"response.completed", "response.incomplete"}
            for frame in frames
        )
        if storage_mode == "gateway":
            response_id = next(
                frame["response"]["id"]
                for frame in frames
                if frame["type"] == "response.created"
            )
            assert (await client.get(f"/v1/responses/{response_id}")).status_code == 404


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("normalization", ["off", "shadow", "on"])
async def test_chat_preserves_native_sources_and_generated_file_references(
    mode, normalization
):
    seen = []
    inline = {
        "sources": {"1": {"url": "https://example.test/source", "title": "Source"}}
    }
    files = [{"id": "generated-image", "mime": "image/png", "target": "image"}]
    execution = {"name": "image_generate", "status": "success"}

    def handle(request):
        seen.append(request)
        assert request.method == "POST", (
            "reference-only Chat must not fetch image bytes"
        )
        if mode == "v1":
            payload = {
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Answer [sources=[1]]",
                            "inline_data": inline,
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            }
        else:
            payload = {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {"text": "Answer [sources=[1]]", "inline_data": inline},
                            {"files": files},
                            {"tool_execution": execution},
                        ],
                    }
                ],
                "finish_reason": "stop",
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            }
        payload.update(created=1, model="test-model", object="chat.completion")
        return httpx2.Response(200, json=payload)

    async with sdk_app(handle, normalization=normalization) as (client, _):
        response = await client.post(
            f"/{mode}/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
    assert response.status_code == 200, response.text
    message = response.json()["choices"][0]["message"]
    assert "[sources=" not in message["content"]
    assert message["content"].count("https://example.test/source") == 1
    assert message["inline_data"] == inline
    if mode == "v2":
        assert message["files"] == files
        assert message["tool_executions"] == [execution]
    assert len(seen) == 1


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("normalization", ["off", "shadow", "on"])
@pytest.mark.parametrize("include_parameters", [False, True])
async def test_flat_input_schema_preserves_precedence_at_sdk_boundary(
    mode, normalization, include_parameters
):
    seen = []
    schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }

    def handle(request):
        seen.append(json.loads(request.content))
        payload = (
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            if mode == "v1"
            else {
                "messages": [{"role": "assistant", "content": [{"text": "ok"}]}],
                "finish_reason": "stop",
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
        )
        payload.update(created=1, model="test-model", object="chat.completion")
        return httpx2.Response(200, json=payload)

    tool = {"type": "function", "name": "weather", "input_schema": schema}
    if include_parameters:
        tool["parameters"] = {
            "type": "object",
            "properties": {"ignored": {"type": "number"}},
        }
    async with sdk_app(handle, normalization=normalization) as (client, _):
        response = await client.post(
            f"/{mode}/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [tool],
            },
        )
    assert response.status_code == 200, response.text
    sent = seen[0]
    if mode == "v1":
        assert sent["functions"][0]["parameters"] == schema
    else:
        assert (
            sent["tools"][0]["functions"]["specifications"][0]["parameters"] == schema
        )


async def test_responses_image_bytes_consumer_still_hydrates_generated_files():
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            assert request.url.path.endswith("/files/generated-image/content")
            return httpx2.Response(200, content=b"image-bytes")
        return httpx2.Response(
            200,
            json={
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "tool_execution": {
                                    "name": "image_generate",
                                    "status": "success",
                                }
                            },
                            {
                                "files": [
                                    {
                                        "id": "generated-image",
                                        "mime": "image/png",
                                        "target": "image",
                                    }
                                ]
                            },
                        ],
                    }
                ],
                "finish_reason": "stop",
                "model": "test-model",
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            },
        )

    async with sdk_app(handle) as (client, _):
        response = await client.post(
            "/v2/responses",
            json={
                "model": "test-model",
                "input": "Draw an image",
                "tools": [{"type": "image_generation"}],
            },
        )
    assert response.status_code == 200, response.text
    image = next(
        item
        for item in response.json()["output"]
        if item["type"] == "image_generation_call"
    )
    assert image["result"] == "aW1hZ2UtYnl0ZXM="
    assert [method for method, _ in seen] == ["POST", "GET"]


@pytest.mark.parametrize("mode", ["v1", "v2"])
async def test_repeated_interrupted_sdk_streams_release_processor_buffers(mode):
    streams = []

    class Interrupted(httpx2.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            text = "answer [sources=[" + "1" * 10_000
            chunk = (
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": text},
                            "finish_reason": None,
                        }
                    ],
                    "created": 1,
                    "model": "test-model",
                    "object": "chat.completion.chunk",
                }
                if mode == "v1"
                else {"messages": [{"role": "assistant", "content": [{"text": text}]}]}
            )
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            raise httpx2.ReadError("synthetic interruption")

        async def aclose(self):
            self.closed = True

    def handle(request):
        stream = Interrupted()
        streams.append(stream)
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )

    async with sdk_app(handle) as (client, app):
        for _ in range(20):
            response = await client.post(
                f"/{mode}/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )
            assert response.status_code == 200
            assert '"error"' in response.text
            assert app.state.response_processor._stream_reasoning_parsers == {}
            assert app.state.response_processor._stream_source_renderers == {}
    assert len(streams) == 20
    assert all(stream.closed for stream in streams)
