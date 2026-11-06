"""Real alpha SDK boundaries through the mounted application, without sockets."""

import json
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest
from gigachat import GigaChat
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor


@asynccontextmanager
async def sdk_app(handler, *, normalization="on", fallback=True):
    config = ProxyConfig(
        proxy=ProxySettings(
            mode="DEV",
            pass_model=True,
            normalization_mode=normalization,
            legacy_chat_fallback=fallback,
        ),
        gigachat={"model": "test-model", "max_retries": 0},
    )
    app = create_app(config)
    app.state.logger = logger
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
    assert errors[0]["code"] == "stream_interrupted"
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
    assert "stream_interrupted" in response.text
    assert '"finish_reason": "tool_calls"' not in response.text
    assert '"finish_reason": "function_call"' not in response.text
    assert "finishReason" not in response.text
    assert "message_stop" not in response.text
    assert stream.closed
