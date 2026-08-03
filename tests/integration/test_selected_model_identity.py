"""One selected-model identity across I1 execution and machine contracts."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import Request
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionResponse

from gpt2giga.app.factory import create_app
from gpt2giga.app.responses_execution import NormalizedBridgeResponsesExecutor
from gpt2giga.models.config import ProxyConfig


class _AChat:
    def __init__(self) -> None:
        self.create_calls = []

    async def create(self, payload):
        self.create_calls.append(payload)
        return ChatCompletionResponse.model_validate(
            {
                "model": "GigaChat-2-Max",
                "messages": [{"role": "assistant", "content": [{"text": "selected"}]}],
                "finish_reason": "stop",
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
        )


class _GigaChat:
    def __init__(self) -> None:
        self.achat = _AChat()
        self.model_calls = 0

    async def aget_models(self):
        self.model_calls += 1
        return SimpleNamespace(
            data=[
                {
                    "id": "GigaChat-2-Max",
                    "owned_by": "gigachat",
                    "type": "chat",
                },
                {
                    "id": "GigaChat-2-Pro",
                    "owned_by": "gigachat",
                    "type": "chat",
                },
            ]
        )

    async def aclose(self) -> None:
        return None


class _RecordingObservabilitySink:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, name, attributes=None, *, context=None, events=None):
        self.events.append((name, attributes or {}, context, list(events or [])))

    async def flush(self) -> None:
        return None


def test_selected_model_identity_and_revisions_are_bound_everywhere(
    monkeypatch,
) -> None:
    giga_client = _GigaChat()
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client",
        lambda _settings: giga_client,
    )
    app = create_app(
        ProxyConfig(
            gigachat={"model": "GigaChat-2-Max"},
            proxy={
                "gigachat_api_mode": "v2",
                "model_max_connections": {"GigaChat-2-Max": 1},
            },
        )
    )

    @app.post("/_test/normalized-responses")
    async def normalized_responses(request: Request):
        return await NormalizedBridgeResponsesExecutor().execute(
            request,
            await request.json(),
        )

    observability = _RecordingObservabilitySink()
    with TestClient(app) as client:
        app.state.observability_sink = observability
        response = client.post(
            "/_test/normalized-responses",
            json={"model": "GigaChat-2-Max", "input": "hello"},
        )
        models = client.get("/models")
        bridge_models = client.get("/bridge/models")
        capabilities = client.get(
            "/bridge/capabilities",
            params={
                "model": "GigaChat-2-Max",
                "protocol": "openai_responses",
                "api_mode": "v2",
            },
        )

    assert response.status_code == 200
    assert response.json()["model"] == "GigaChat-2-Max"
    assert giga_client.achat.create_calls[0].model == "GigaChat-2-Max"
    assert "GigaChat-2-Max" in app.state.model_concurrency_limiter._semaphores

    assert models.status_code == 200
    assert {model["id"] for model in models.json()["data"]} == {
        "GigaChat-2-Max",
        "GigaChat-2-Pro",
    }
    assert bridge_models.status_code == 200
    bridge_body = bridge_models.json()
    assert {model["id"] for model in bridge_body["models"]} == {
        "GigaChat-2-Max",
        "GigaChat-2-Pro",
    }

    assert capabilities.status_code == 200
    capability_body = capabilities.json()
    assert capability_body["model"] == "GigaChat-2-Max"
    assert capability_body["inventory_revision"] == bridge_body["inventory_revision"]

    _name, _attributes, context, _events = observability.events[0]
    assert context.model_effective == "GigaChat-2-Max"
    assert context.metadata["selected_model_id"] == "GigaChat-2-Max"
    assert context.metadata["inventory_revision"] == bridge_body["inventory_revision"]
    assert (
        context.metadata["effective_capability_revision"]
        == capability_body["capability_revision"]
    )
    assert context.metadata["admission_schema_version"] == (
        "gpt2giga.bridge-admission.v1"
    )
    assert (
        context.metadata["admission_loss_matrix_revision"]
        == bridge_body["matrix_revision"]
    )
    assert giga_client.model_calls == 1
