"""Pinned Codex Responses conformance through the normalized GigaChat route."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
import pytest

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.routers.openai.responses import router as responses_router


CORPUS_ROOT = Path(__file__).parents[1] / "corpora" / "bridge" / "v1"
CODEX_MIN_VERSION = (0, 146, 0)
CODEX_MAX_VERSION = (0, 147, 0)


def _load(name: str) -> dict:
    return json.loads(CORPUS_ROOT.joinpath(name).read_text(encoding="utf-8"))


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return self._payload


class _GigaChat:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.stream_calls: list[dict] = []
        self.stream_chunks_yielded = 0
        self.stream_closed = False

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
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            }
        )

    def astream(self, payload: dict) -> AsyncIterator[_Response]:
        self.stream_calls.append(payload)

        async def generate() -> AsyncIterator[_Response]:
            try:
                self.stream_chunks_yielded += 1
                yield _Response(
                    {
                        "choices": [
                            {
                                "delta": {"content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 1,
                            "total_tokens": 6,
                        },
                    }
                )
            finally:
                self.stream_closed = True

        return generate()


class _Transformer:
    def __init__(self) -> None:
        self.chat_calls: list[dict] = []

    async def prepare_chat(self, payload: dict, giga_client=None) -> dict:
        self.chat_calls.append(payload)
        return payload


def _app() -> tuple[FastAPI, _GigaChat, _Transformer]:
    app = FastAPI()
    app.include_router(responses_router, prefix="/v1")
    giga_client = _GigaChat()
    transformer = _Transformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v1"),
        gigachat={"model": "GigaChat-2-Max"},
    )
    app.state.gigachat_client = giga_client
    app.state.logger = logger
    app.state.model_concurrency_limiter = ModelConcurrencyLimiter({})
    app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
    app.state.request_transformer = transformer
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app, giga_client, transformer


def _event_types(body: str) -> list[str]:
    return [
        line.removeprefix("event: ")
        for line in body.splitlines()
        if line.startswith("event: ")
    ]


def test_codex_corpus_pins_reviewed_responses_version_window() -> None:
    corpus = _load("codex_responses_sequence.json")
    version = _version_tuple(corpus["client"]["version"])

    assert CODEX_MIN_VERSION <= version < CODEX_MAX_VERSION
    assert corpus["client"] == {
        "name": "codex-cli",
        "version": "0.146.0",
        "wire_api": "responses",
    }
    assert corpus["config"]["model_providers.gpt2giga"]["wire_api"] == "responses"
    assert corpus["request"]["path"] == "/v1/responses"


def test_codex_corpus_reaches_gigachat_with_tools_schema_and_usage() -> None:
    body = dict(_load("codex_responses_sequence.json")["request"]["body"])
    body["stream"] = False
    body["text"] = {
        "format": {
            "type": "json_schema",
            "name": "answer",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
            "strict": True,
        }
    }
    app, giga_client, transformer = _app()

    response = TestClient(app).post("/v1/responses", json=body)

    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "ok"
    assert response.json()["usage"] == {
        "input_tokens": 5,
        "output_tokens": 1,
        "total_tokens": 6,
    }
    assert len(giga_client.calls) == 1
    assert transformer.chat_calls[0]["tools"][0]["function"]["name"] == "weather"
    assert transformer.chat_calls[0]["response_format"]["json_schema"] == {
        "name": "answer",
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        "strict": True,
    }


def test_codex_corpus_stream_matches_pinned_event_lifecycle() -> None:
    corpus = _load("codex_responses_sequence.json")
    app, giga_client, transformer = _app()

    with TestClient(app).stream(
        "POST",
        corpus["request"]["path"],
        json=corpus["request"]["body"],
    ) as response:
        payload = "".join(response.iter_text())

    assert response.status_code == 200
    assert _event_types(payload) == corpus["expected_event_types"]
    assert '"text": "ok"' in payload
    assert '"total_tokens": 6' in payload
    assert len(giga_client.stream_calls) == 1
    assert len(transformer.chat_calls) == 1
    assert giga_client.stream_closed is True


@pytest.mark.parametrize(
    "field",
    _load("unsupported_fields.json")["expected"]["rejected_fields"],
)
def test_codex_unrepresentable_fields_fail_before_gigachat_io(field: str) -> None:
    fixture = _load("unsupported_fields.json")
    value = fixture["request"][field]
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        "/v1/responses",
        json={"input": "hello", "model": "bridge/codex-test", field: value},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == fixture["expected"]["code"]
    assert response.json()["error"]["param"] == field
    assert giga_client.calls == []
    assert giga_client.stream_calls == []
    assert transformer.chat_calls == []


async def test_codex_disconnect_closes_exact_gigachat_stream_without_terminal() -> None:
    corpus = _load("codex_responses_sequence.json")
    app, giga_client, transformer = _app()
    normalized = OpenAIProtocolAdapter().responses_to_normalized(
        corpus["request"]["body"]
    )
    adapter = GigaChatProviderAdapter(
        config=app.state.config,
        request_transformer=transformer,
        giga_client=giga_client,
        model_limiter=app.state.model_concurrency_limiter,
        response_processor=app.state.response_processor,
        api_mode="v1",
        forced_model="GigaChat-2-Max",
    )

    events = [
        event
        async for event in adapter.stream_chat(
            normalized,
            is_disconnected=lambda: True,
        )
    ]

    assert [event.type for event in events] == ["message_start"]
    assert not {event.type for event in events} & {"message_end", "error"}
    assert len(giga_client.stream_calls) == 1
    assert giga_client.stream_chunks_yielded == 1
