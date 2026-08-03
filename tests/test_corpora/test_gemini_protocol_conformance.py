"""Pinned Gemini GenerateContent protocol conformance.

The pinned client is google-genai Python. These tests intentionally make no
claim that native Gemini CLI accepts an arbitrary custom endpoint.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.gemini import (
    GeminiProtocolAdapter,
    normalized_chat_response_to_gemini,
)
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.routers.gemini import router as gemini_router


CORPUS_ROOT = Path(__file__).parents[1] / "corpora" / "bridge" / "v1"
GOOGLE_GENAI_MIN_VERSION = (2, 14, 0)
GOOGLE_GENAI_MAX_VERSION = (2, 15, 0)


def _load(name: str) -> dict:
    return json.loads(CORPUS_ROOT.joinpath(name).read_text(encoding="utf-8"))


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _sse_payloads(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
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
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
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
                            "delta": {"content": "Hello"},
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                }
            )
            yield _Response(
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
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
    app.include_router(gemini_router)
    giga_client = _GigaChat()
    transformer = _Transformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v1"),
    )
    app.state.gigachat_client = giga_client
    app.state.logger = logger
    app.state.model_concurrency_limiter = ModelConcurrencyLimiter({})
    app.state.request_transformer = transformer
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.gemini_protocol_adapter = GeminiProtocolAdapter()
    return app, giga_client, transformer


def test_gemini_corpus_pins_reviewed_sdk_window_not_cli_support() -> None:
    corpus = _load("gemini_sdk_generate_content_request.json")
    client = corpus["client"]
    version = _version_tuple(client["version"])

    assert GOOGLE_GENAI_MIN_VERSION <= version < GOOGLE_GENAI_MAX_VERSION
    assert client == {"name": "google-genai-python", "version": "2.14.0"}
    assert client["name"] != "gemini-cli"
    assert corpus["request"]["path"] == ("/models/bridge/gemini-test:generateContent")


def test_gemini_corpus_normalizes_system_contents_generation_and_tools() -> None:
    body = _load("gemini_sdk_generate_content_request.json")["request"]["body"]

    normalized = GeminiProtocolAdapter().generate_content_to_normalized(
        body,
        model="bridge/gemini-test",
    )

    assert normalized.protocol == "gemini"
    assert normalized.operation == "chat"
    assert normalized.model == "bridge/gemini-test"
    assert [message.role for message in normalized.messages] == ["system", "user"]
    assert normalized.messages[0].content == "Be concise."
    assert normalized.messages[1].content == "Weather in Moscow?"
    assert normalized.generation_config.max_tokens == 64
    assert normalized.generation_config.temperature == 0
    assert normalized.tools[0].name == "weather"
    assert normalized.tools[0].parameters["required"] == ["city"]


def test_gemini_corpus_nonstream_crosses_public_facade() -> None:
    fixture = _load("gemini_sdk_generate_content_request.json")["request"]
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        fixture["path"],
        json=fixture["body"],
        headers=fixture["headers"],
    )

    assert response.status_code == 200
    assert response.json()["candidates"][0] == {
        "index": 0,
        "content": {"role": "model", "parts": [{"text": "Hello"}]},
        "finishReason": "STOP",
        "safetyRatings": [],
    }
    assert response.json()["usageMetadata"] == {
        "promptTokenCount": 2,
        "candidatesTokenCount": 1,
        "totalTokenCount": 3,
    }
    assert len(giga_client.calls) == 1
    assert transformer.chat_calls[0]["tools"][0]["function"]["name"] == "weather"


def test_gemini_corpus_stream_matches_generate_content_chunks() -> None:
    request = _load("gemini_sdk_generate_content_request.json")["request"]
    expected = _load("gemini_stream_sequence.json")
    path = request["path"].replace(":generateContent", ":streamGenerateContent")
    app, giga_client, _transformer = _app()

    with TestClient(app).stream(
        "POST",
        path,
        json=request["body"],
        headers=request["headers"],
    ) as response:
        chunks = _sse_payloads("".join(response.iter_text()))

    assert response.status_code == 200
    assert len(chunks) == len(expected["chunks"])
    assert chunks[0]["candidates"] == expected["chunks"][0]["candidates"]
    assert chunks[1]["candidates"] == expected["chunks"][1]["candidates"]
    assert chunks[1]["usageMetadata"] == expected["chunks"][1]["usageMetadata"]
    terminal_reason = expected["terminal"]["finishReason"]
    assert (
        sum(
            candidate.get("finishReason") == terminal_reason
            for chunk in chunks
            for candidate in chunk["candidates"]
        )
        == expected["terminal"]["max_count"]
    )
    assert len(giga_client.stream_calls) == 1


def test_gemini_function_call_remains_native_in_public_response() -> None:
    payload = normalized_chat_response_to_gemini(
        NormalizedResponse(
            id="response-1",
            model="bridge/gemini-test",
            choices=[
                NormalizedChoice(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                id="call-1",
                                name="weather",
                                arguments={"city": "Moscow"},
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=NormalizedUsage(input_tokens=2, output_tokens=1, total_tokens=3),
        ),
        requested_model="bridge/gemini-test",
    )

    assert payload["candidates"][0]["content"] == {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "id": "call-1",
                    "name": "weather",
                    "args": {"city": "Moscow"},
                }
            }
        ],
    }
    assert payload["candidates"][0]["finishReason"] == "STOP"
