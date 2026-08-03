"""Pinned Claude Anthropic-gateway protocol conformance.

These tests assert gateway wire facts only; they do not claim agent-level Claude
Code support for arbitrary providers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.anthropic import (
    AnthropicProtocolAdapter,
    AnthropicStreamProjector,
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.routers.anthropic import router as anthropic_router


CORPUS_ROOT = Path(__file__).parents[1] / "corpora" / "bridge" / "v1"
CLAUDE_MIN_VERSION = (2, 1, 212)
CLAUDE_MAX_VERSION = (2, 2, 0)
ANTHROPIC_SDK_MIN_VERSION = (0, 120, 2)
ANTHROPIC_SDK_MAX_VERSION = (0, 121, 0)


def _load(name: str) -> dict:
    return json.loads(CORPUS_ROOT.joinpath(name).read_text(encoding="utf-8"))


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _event_types(body: str) -> list[str]:
    return [
        line.removeprefix("event: ")
        for line in body.splitlines()
        if line.startswith("event: ")
    ]


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return self._payload


class _GigaChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.stream_calls: list[dict] = []

    async def achat(self, payload: dict) -> _Response:
        self.calls.append(payload)
        return _Response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            }
        )

    def astream(self, payload: dict) -> AsyncIterator[_Response]:
        self.stream_calls.append(payload)

        async def generate() -> AsyncIterator[_Response]:
            yield _Response(
                {
                    "choices": [
                        {
                            "delta": {"content": "ok"},
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                }
            )
            yield _Response(
                {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 1,
                        "total_tokens": 4,
                    },
                }
            )

        return generate()


class _Transformer:
    def __init__(self) -> None:
        self.chat_calls: list[dict] = []

    async def prepare_chat(self, payload: dict, giga_client=None) -> dict:
        self.chat_calls.append(payload)
        return payload


def _app() -> tuple[FastAPI, _GigaChat, _Transformer]:
    app = FastAPI()
    app.include_router(anthropic_router, prefix="/v1")
    giga_client = _GigaChat()
    transformer = _Transformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode="v1",
            legacy_chat_fallback=False,
            normalization_mode="on",
        )
    )
    app.state.gigachat_client = giga_client
    app.state.logger = logger
    app.state.model_concurrency_limiter = ModelConcurrencyLimiter({})
    app.state.request_transformer = transformer
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.captured_headers = {}

    @app.middleware("http")
    async def capture_gateway_headers(request: Request, call_next):
        app.state.captured_headers = {
            name: request.headers.get(name)
            for name in ("anthropic-version", "content-type", "x-api-key")
        }
        return await call_next(request)

    return app, giga_client, transformer


def test_claude_corpus_pins_reviewed_client_and_sdk_windows() -> None:
    corpus = _load("claude_code_anthropic_request.json")
    client = corpus["client"]
    sdk = client["compatible_sdk"]

    assert (
        CLAUDE_MIN_VERSION <= _version_tuple(client["version"]) < (CLAUDE_MAX_VERSION)
    )
    assert (
        ANTHROPIC_SDK_MIN_VERSION
        <= _version_tuple(sdk["version"])
        < (ANTHROPIC_SDK_MAX_VERSION)
    )
    assert client["wire_api"] == "anthropic-messages"
    assert corpus["request"]["path"] == "/v1/messages"


def test_claude_corpus_preserves_roles_model_alias_and_named_tool() -> None:
    body = _load("claude_code_anthropic_request.json")["request"]["body"]

    normalized = AnthropicProtocolAdapter().messages_to_normalized(body)

    assert normalized.protocol == "anthropic"
    assert normalized.model == "bridge/anthropic-test"
    assert normalized.stream is True
    assert [message.role for message in normalized.messages] == ["system", "user"]
    assert normalized.messages[0].content == "Be concise."
    assert normalized.messages[1].to_json_dict()["content"] == [
        {
            "type": "text",
            "text": "Weather in Moscow?",
            "raw_extensions": {},
            "provider_metadata": {},
        }
    ]
    assert normalized.tools[0].name == "weather"
    assert normalized.tool_choice == {
        "type": "function",
        "function": {"name": "weather"},
    }


def test_claude_corpus_headers_and_usage_cross_the_normalized_gateway() -> None:
    fixture = _load("claude_code_anthropic_request.json")["request"]
    body = {**fixture["body"], "stream": False}
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        fixture["path"],
        json=body,
        headers=fixture["headers"],
    )

    assert response.status_code == 200
    assert response.json()["content"] == [{"type": "text", "text": "ok"}]
    assert response.json()["model"] == "bridge/anthropic-test"
    assert response.json()["usage"] == {"input_tokens": 3, "output_tokens": 1}
    assert app.state.captured_headers == fixture["headers"]
    assert len(giga_client.calls) == 1
    assert transformer.chat_calls[0]["messages"][0] == {
        "role": "system",
        "content": "Be concise.",
    }
    assert transformer.chat_calls[0]["tools"][0]["function"]["name"] == "weather"


def test_claude_corpus_stream_matches_messages_lifecycle() -> None:
    fixture = _load("claude_code_anthropic_request.json")["request"]
    expected = _load("anthropic_stream_sequence.json")
    app, giga_client, _transformer = _app()

    with TestClient(app).stream(
        "POST",
        fixture["path"],
        json=fixture["body"],
        headers=fixture["headers"],
    ) as response:
        payload = "".join(response.iter_text())

    assert response.status_code == 200
    assert _event_types(payload) == expected["events"]
    assert _event_types(payload).count(expected["terminal"]["event"]) == 1
    assert '"text": "ok"' in payload
    assert len(giga_client.stream_calls) == 1


def test_claude_tool_and_error_shapes_remain_anthropic_native() -> None:
    tool_response = normalized_chat_response_to_anthropic(
        NormalizedResponse(
            id="request-1",
            model="bridge/anthropic-test",
            choices=[
                NormalizedChoice(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                id="toolu-1",
                                name="weather",
                                arguments={"city": "Moscow"},
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=NormalizedUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        ),
        requested_model="bridge/anthropic-test",
    )

    assert tool_response["content"] == [
        {
            "type": "tool_use",
            "id": "toolu-1",
            "name": "weather",
            "input": {"city": "Moscow"},
        }
    ]
    assert tool_response["stop_reason"] == "tool_use"
    assert tool_response["usage"] == {"input_tokens": 3, "output_tokens": 2}

    frame = AnthropicStreamProjector(
        requested_model="bridge/anthropic-test",
        response_id="request-1",
    ).project(
        NormalizedStreamEvent(
            type="error",
            error=NormalizedError(
                type="api_error",
                message="upstream failed",
                code="provider_failure",
            ),
        )
    )[0]
    assert frame.startswith("event: error\n")
    assert json.loads(frame.splitlines()[1].removeprefix("data: ")) == {
        "type": "error",
        "error": {
            "type": "api_error",
            "message": "upstream failed",
            "code": "provider_failure",
        },
    }
