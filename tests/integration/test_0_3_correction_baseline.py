"""Freeze the 0.3 Responses and model-inventory correction baseline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from gpt2giga.app.factory import create_app
from gpt2giga.core.context import RequestContext
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocols.normalized import NormalizedChatRequest
from gpt2giga.protocols.openai import OpenAIProtocolAdapter


class _ProviderModel(BaseModel):
    id_: str = Field(alias="id")
    object_: str = Field(default="model", alias="object")
    owned_by: str = "gigachat"


class _ProviderModels(BaseModel):
    data: list[_ProviderModel]
    object_: str = "list"


class _RecordingGigaChatClient:
    def __init__(self) -> None:
        self.discovery_calls: list[str] = []
        self.response_calls: list[Any] = []

    async def aget_models(self) -> _ProviderModels:
        self.discovery_calls.append("aget_models")
        return _ProviderModels(
            data=[
                _ProviderModel(id="GigaChat-2-Max"),
                _ProviderModel(id="GigaChat-2-Pro"),
                _ProviderModel(id="GigaChat-2-Lite"),
            ]
        )

    async def achat(self, payload: Any) -> Any:
        self.response_calls.append(payload)
        return _ProviderResponse()

    async def aclose(self) -> None:
        return None


class _ProviderResponse:
    def model_dump(self) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "native"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 1,
                "total_tokens": 3,
            },
        }


class _RecordingOpenAIProtocolAdapter(OpenAIProtocolAdapter):
    def __init__(self) -> None:
        self.responses_requests: list[dict[str, Any]] = []

    async def responses_to_normalized_async(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> NormalizedChatRequest:
        self.responses_requests.append(dict(payload))
        return await super().responses_to_normalized_async(payload, context=context)


def _correction_baseline_app(
    monkeypatch,
    *,
    config: ProxyConfig | None = None,
) -> tuple[Any, _RecordingGigaChatClient, _RecordingOpenAIProtocolAdapter]:
    provider = _RecordingGigaChatClient()
    adapter = _RecordingOpenAIProtocolAdapter()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: provider,
    )
    app = create_app(config or ProxyConfig(gigachat={"model": None}))
    app.state.openai_protocol_adapter = adapter
    return app, provider, adapter


def test_hosted_tool_uses_native_default_without_normalized_decode(
    monkeypatch,
) -> None:
    app, provider, adapter = _correction_baseline_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/responses",
            json={
                "model": "GigaChat",
                "input": "Find current documentation.",
                "tools": [{"type": "web_search_preview"}],
            },
        )

    assert app.state.legacy_responses_enabled is False
    assert adapter.responses_requests == []
    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "native"
    assert provider.discovery_calls == []
    assert len(provider.response_calls) == 1


def test_attachment_uses_native_default_without_normalized_decode(
    monkeypatch,
) -> None:
    app, provider, adapter = _correction_baseline_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/responses",
            headers={"x-gpt2giga-attachment-ids": "file-pdf-1"},
            json={"model": "GigaChat", "input": "Summarize the attachment."},
        )

    assert app.state.legacy_responses_enabled is False
    assert adapter.responses_requests == []
    assert response.status_code == 200
    assert response.json()["output"][0]["content"][0]["text"] == "native"
    assert provider.discovery_calls == []
    assert len(provider.response_calls) == 1


def test_baseline_models_and_bridge_models_publish_different_inventories(
    monkeypatch,
) -> None:
    app, provider, _adapter = _correction_baseline_app(monkeypatch)

    with TestClient(app) as client:
        models_response = client.get("/models")
        bridge_response = client.get("/bridge/models")

    assert models_response.status_code == 200
    assert [model["id"] for model in models_response.json()["data"]] == [
        "GigaChat-2-Max",
        "GigaChat-2-Pro",
        "GigaChat-2-Lite",
    ]
    assert bridge_response.status_code == 200
    assert [model["public_alias"] for model in bridge_response.json()["models"]] == [
        "GigaChat"
    ]
    assert provider.discovery_calls == ["aget_models"]
    assert provider.response_calls == []


def test_baseline_gigachat_model_env_hides_other_models_from_bridge_inventory(
    monkeypatch,
) -> None:
    monkeypatch.delenv("GPT2GIGA_CONFIG", raising=False)
    monkeypatch.setenv("GIGACHAT_MODEL", "GigaChat-2-Max")
    config = ProxyConfig()
    app, provider, _adapter = _correction_baseline_app(monkeypatch, config=config)

    with TestClient(app) as client:
        models_response = client.get("/models")
        bridge_response = client.get("/bridge/models")

    assert config.gigachat_settings.model == "GigaChat-2-Max"
    assert models_response.status_code == 200
    assert [model["id"] for model in models_response.json()["data"]] == [
        "GigaChat-2-Max",
        "GigaChat-2-Pro",
        "GigaChat-2-Lite",
    ]
    assert bridge_response.status_code == 200
    assert [model["public_alias"] for model in bridge_response.json()["models"]] == [
        "GigaChat-2-Max"
    ]
    assert provider.discovery_calls == ["aget_models"]
    assert provider.response_calls == []
