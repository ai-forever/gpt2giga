"""Integrated hosted-tool parity for the normalized GigaChat v2 route."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionChunk, ChatCompletionResponse

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocols.openai import (
    ResponsesStreamProjector,
    normalized_chat_response_to_responses,
)


class _AChat:
    def __init__(self) -> None:
        self.create_calls = []
        self.stream_calls = []

    async def create(self, payload):
        self.create_calls.append(payload)
        return ChatCompletionResponse.model_validate(_hosted_response_payload())

    def stream(self, payload):
        self.stream_calls.append(payload)

        async def generate():
            yield ChatCompletionChunk.model_validate(_hosted_response_payload())

        return generate()


class _GigaChat:
    def __init__(self) -> None:
        self.achat = _AChat()

    async def aclose(self) -> None:
        return None


def _hosted_response_payload() -> dict:
    return {
        "model": "GigaChat-2-Max",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"tool_execution": {"name": "web_search", "status": "success"}},
                    {
                        "inline_data": {
                            "sources": {"1": {"url": "https://example.test/source"}}
                        }
                    },
                ],
            }
        ],
        "finish_reason": "stop",
        "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
    }


def _request_payload(*, stream: bool = False) -> dict:
    return {
        "model": "GigaChat-2-Max",
        "input": "Find a source",
        "stream": stream,
        "tools": [{"type": "web_search_preview"}],
        "tool_choice": {"type": "web_search_preview"},
    }


async def test_normalized_hosted_tool_nonstream_parity(monkeypatch) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )
    app = create_app(
        ProxyConfig(
            gigachat={"model": "GigaChat-2-Max"},
            proxy={"gigachat_api_mode": "v2"},
        )
    )
    request_payload = _request_payload()

    with TestClient(app):
        normalized = app.state.openai_protocol_adapter.responses_to_normalized(
            request_payload
        )
        adapter = app.state.bridge_provider_runtime.adapter_for(
            normalized,
            api_mode="v2",
        )
        response = await adapter.chat(normalized)

    provider_request = giga_client.achat.create_calls[0]
    assert provider_request.model == "GigaChat-2-Max"
    assert provider_request.tools[0].web_search.model_dump(exclude_none=True) == {}
    assert provider_request.tool_config.tool_name == "web_search"

    public = normalized_chat_response_to_responses(
        response,
        request_payload=request_payload,
        requested_model=request_payload["model"],
        response_id="hosted",
    )
    assert public["output"] == [
        {
            "id": "ws_hosted",
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "Find a source",
                "sources": [{"type": "url", "url": "https://example.test/source"}],
            },
        }
    ]


async def test_normalized_hosted_tool_stream_parity(monkeypatch) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )
    app = create_app(
        ProxyConfig(
            gigachat={"model": "GigaChat-2-Max"},
            proxy={"gigachat_api_mode": "v2"},
        )
    )
    request_payload = _request_payload(stream=True)

    with TestClient(app):
        normalized = app.state.openai_protocol_adapter.responses_to_normalized(
            request_payload
        )
        adapter = app.state.bridge_provider_runtime.adapter_for(
            normalized,
            api_mode="v2",
        )
        projector = ResponsesStreamProjector(
            request_payload=request_payload,
            requested_model=request_payload["model"],
            response_id="hosted-stream",
            created_at=100,
        )
        frames = []
        async for event in adapter.stream_chat(normalized):
            frames.extend(projector.project(event))
        projector.finish()

    provider_request = giga_client.achat.stream_calls[0]
    assert provider_request.model == "GigaChat-2-Max"
    assert provider_request.tools[0].web_search.model_dump(exclude_none=True) == {}
    event_names = [frame.splitlines()[0].removeprefix("event: ") for frame in frames]
    assert event_names == [
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.output_item.done",
        "response.completed",
    ]
    completed = json.loads(frames[-1].splitlines()[1].removeprefix("data: "))
    assert completed["response"]["output"][0]["type"] == "message"
    assert completed["response"]["output"][1]["type"] == "web_search_call"
    assert completed["response"]["output"][1]["action"]["sources"] == [
        {"type": "url", "url": "https://example.test/source"}
    ]
