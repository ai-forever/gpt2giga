from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from gpt2giga.api.anthropic.request_adapter import (
    build_normalized_chat_request as build_anthropic_request,
)
from gpt2giga.api.anthropic.response import _build_anthropic_response
from gpt2giga.api.gemini.request_adapter import (
    build_normalized_chat_request as build_gemini_request,
)
from gpt2giga.api.gemini.response import build_generate_content_response
from gpt2giga.api.openai.request_adapter import (
    build_normalized_chat_request as build_openai_request,
)
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.providers.gigachat import RequestTransformer, ResponseProcessor

FIXTURES_DIR = Path(__file__).with_name("fixtures")
FIXED_TIME = 1_700_000_000
FIXED_UUID = UUID("12345678-90ab-cdef-1234-567890abcdef")


class _MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


class _DummyLogger:
    def bind(self, *args, **kwargs):
        return self

    def debug(self, *args, **kwargs):
        return None


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _dumpable(value):
    if hasattr(value, "model_dump"):
        return _dumpable(value.model_dump(by_alias=True, exclude_none=True))
    if isinstance(value, dict):
        return {key: _dumpable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dumpable(item) for item in value]
    return value


def _serialize_normalized_request(request) -> dict:
    return _dumpable(
        {
            "model": request.model,
            "messages": [message.to_openai_message() for message in request.messages],
            "stream": request.stream,
            "tools": [tool.to_openai_tool() for tool in request.tools],
            "options": request.options,
        }
    )


@pytest.mark.asyncio
async def test_openai_golden_chat_contract(monkeypatch):
    fixture = _load_fixture("openai_chat.json")
    request = build_openai_request(fixture["incoming_request"])

    assert _serialize_normalized_request(request) == fixture["normalized_request"]

    transformer = RequestTransformer(ProxyConfig(), _DummyLogger())
    prepared = await transformer.prepare_chat_completion(request)
    assert _dumpable(prepared) == fixture["backend_payload"]

    monkeypatch.setattr(
        "gpt2giga.providers.gigachat.response_mapper.time.time",
        lambda: FIXED_TIME,
    )
    monkeypatch.setattr(
        "gpt2giga.providers.gigachat.response_mapper.uuid.uuid4",
        lambda: FIXED_UUID,
    )
    response = ResponseProcessor(_DummyLogger()).process_response(
        _MockResponse(fixture["backend_response"]),
        request.model,
        "resp-openai",
    )

    assert response == fixture["external_response"]


@pytest.mark.asyncio
async def test_anthropic_golden_messages_contract(monkeypatch):
    fixture = _load_fixture("anthropic_messages.json")
    request = build_anthropic_request(fixture["incoming_request"])

    assert _serialize_normalized_request(request) == fixture["normalized_request"]

    transformer = RequestTransformer(ProxyConfig(), _DummyLogger())
    prepared = await transformer.prepare_chat_completion(request)
    assert _dumpable(prepared) == fixture["backend_payload"]

    monkeypatch.setattr(
        "gpt2giga.api.anthropic.response.uuid.uuid4",
        lambda: FIXED_UUID,
    )
    response = _build_anthropic_response(
        fixture["backend_response"],
        request.model,
        "resp-anthropic",
    )

    assert response == fixture["external_response"]


@pytest.mark.asyncio
async def test_gemini_golden_generate_content_contract():
    fixture = _load_fixture("gemini_generate_content.json")
    request = build_gemini_request(fixture["incoming_request"])

    assert _serialize_normalized_request(request) == fixture["normalized_request"]

    transformer = RequestTransformer(ProxyConfig(), _DummyLogger())
    prepared = await transformer.prepare_chat_completion(request)
    assert _dumpable(prepared) == fixture["backend_payload"]

    response = build_generate_content_response(
        fixture["backend_response"],
        request.model,
        "resp-gemini",
        request_data=fixture["incoming_request"],
    )

    assert response == fixture["external_response"]
