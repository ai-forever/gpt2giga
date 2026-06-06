import copy
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocol.anthropic.response import _build_anthropic_response
from gpt2giga.protocol.embeddings import (
    apply_embedding_encoding_format,
    normalize_embedding_response,
)
from gpt2giga.routers.anthropic import router as anthropic_router

FIXTURES = Path(__file__).resolve().parents[1] / "golden"


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeAnthropicGigachat:
    def astream(self, chat):
        async def gen():
            yield MockResponse(
                {"choices": [{"delta": {"content": "Hel"}}], "usage": None}
            )
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "lo!"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }
            )

        return gen()


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {"model": data.get("model", "giga"), "messages": data.get("messages")}


def _load_json(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def _load_text(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def _response(data: dict) -> SimpleNamespace:
    return SimpleNamespace(model_dump=lambda: data)


def _normalize_openai_dynamic_fields(body: dict) -> dict:
    normalized = copy.deepcopy(body)
    normalized["created"] = 0
    for choice in normalized.get("choices", []):
        message = choice.get("message") or choice.get("delta") or {}
        for tool_call in message.get("tool_calls", []):
            tool_call["id"] = "<tool_call_id>"
    return normalized


def _processor() -> ResponseProcessor:
    return ResponseProcessor(logger=logger, mode="PROD")


def test_openai_chat_basic_matches_golden_fixture():
    body = _processor().process_response(
        _response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        ),
        "gpt-x",
        "golden-chat",
    )

    assert _normalize_openai_dynamic_fields(body) == _load_json(
        "openai/chat_basic.json"
    )


def test_openai_chat_tools_matches_golden_fixture():
    body = _processor().process_response(
        _response(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "function_call": {
                                "name": "get_weather",
                                "arguments": {"city": "Moscow"},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            }
        ),
        "gpt-x",
        "golden-tools",
    )

    assert _normalize_openai_dynamic_fields(body) == _load_json(
        "openai/chat_tools.json"
    )


def test_openai_chat_structured_output_matches_golden_fixture():
    body = _processor().process_response(
        _response(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "function_call": {
                                "name": "final_answer",
                                "arguments": {"answer": "ok", "score": 1},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 3,
                    "total_tokens": 7,
                },
            }
        ),
        "gpt-x",
        "golden-structured",
        request_data={
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": {"type": "object"}},
            }
        },
    )

    assert _normalize_openai_dynamic_fields(body) == _load_json(
        "openai/chat_structured_output.json"
    )


def test_openai_chat_streaming_matches_golden_fixture():
    chunk = _processor().process_stream_chunk(
        _response(
            {
                "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
                "usage": None,
            }
        ),
        "gpt-x",
        "golden-stream",
    )
    normalized = _normalize_openai_dynamic_fields(chunk)
    actual = (
        f"data: {json.dumps(normalized, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )

    assert actual == _load_text("openai/chat_streaming.txt")


def test_openai_embeddings_matches_golden_fixture():
    response = {
        "data": [
            {
                "embedding": [0.0, 1.0],
                "index": 0,
                "usage": {"prompt_tokens": 2},
            }
        ],
        "model": "EmbeddingsGigaR",
    }

    actual = apply_embedding_encoding_format(
        normalize_embedding_response(response, model="EmbeddingsGigaR"),
        None,
    )

    assert actual == _load_json("openai/embeddings.json")


def test_anthropic_messages_basic_matches_golden_fixture():
    actual = _build_anthropic_response(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
        "claude-x",
        "golden-anthropic",
        logger=logger,
        mode="PROD",
    )

    assert actual == _load_json("anthropic/messages_basic.json")


def test_anthropic_messages_streaming_matches_golden_fixture():
    app = FastAPI()
    app.include_router(anthropic_router)
    app.state.config = ProxyConfig(
        proxy=ProxySettings(structured_output_mode="function_call")
    )
    app.state.gigachat_client = FakeAnthropicGigachat()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.response_processor = ResponseProcessor(logger=logger, mode="PROD")
    app.state.logger = logger

    client = TestClient(app)
    response = client.post(
        "/messages",
        json={
            "model": "claude-test",
            "max_tokens": 100,
            "stream": True,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 200
    assert response.text == _load_text("anthropic/messages_streaming.txt")
