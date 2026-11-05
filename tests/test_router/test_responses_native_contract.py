"""Regression coverage for native Responses model and completion semantics."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor


class _NativeChat:
    def __init__(self, *, finish_reason="stop", response_model="GigaChat-2-Max"):
        self.finish_reason = finish_reason
        self.response_model = response_model
        self.payloads = []

    async def __call__(self, payload):
        self.payloads.append(payload)
        return SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "model": self.response_model,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "partial text"},
                        "finish_reason": self.finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            }
        )

    async def create(self, payload):
        self.payloads.append(payload)
        return SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "model": self.response_model,
                "messages": [
                    {"role": "assistant", "content": [{"text": "partial text"}]}
                ],
                "finish_reason": self.finish_reason,
                "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            }
        )


def _make_app(*, configured_model="GigaChat-2-Pro", **upstream_options):
    app = create_app(
        config=ProxyConfig(
            proxy=ProxySettings(mode="DEV", pass_model=True),
            gigachat={"model": configured_model},
        )
    )
    upstream = _NativeChat(**upstream_options)
    app.state.gigachat_client = SimpleNamespace(achat=upstream)
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app, upstream


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("response_model", ["GigaChat-2-Max", None])
def test_native_responses_can_omit_model_with_configured_default(mode, response_model):
    app, upstream = _make_app(response_model=response_model)

    response = TestClient(app).post(f"/{mode}/responses", json={"input": "hello"})

    assert response.status_code == 200, response.text
    assert response.json()["model"] == (response_model or "GigaChat-2-Pro")
    assert len(upstream.payloads) == 1


@pytest.mark.parametrize(
    "selection",
    [{"previous_response_id": "resp_thread-1"}, {"assistant_id": "assistant-1"}],
)
def test_native_responses_can_omit_model_with_upstream_selection(selection):
    app, upstream = _make_app(configured_model=None)

    response = TestClient(app).post(
        "/v2/responses", json={"input": "hello", **selection}
    )

    assert response.status_code == 200, response.text
    assert response.json()["model"] == "GigaChat-2-Max"
    assert upstream.payloads[0].model is None


@pytest.mark.parametrize("mode", ["v1", "v2"])
def test_native_responses_keeps_explicit_client_model(mode):
    app, _ = _make_app()

    response = TestClient(app).post(
        f"/{mode}/responses", json={"model": "client-model", "input": "hello"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["model"] == "client-model"


@pytest.mark.parametrize("mode", ["v1", "v2"])
def test_native_responses_missing_model_selection_fails_before_upstream(mode):
    app, upstream = _make_app(configured_model=None)

    response = TestClient(app).post(f"/{mode}/responses", json={"input": "hello"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_required"
    assert not upstream.payloads


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize(
    ("finish_reason", "expected_status", "incomplete_reason"),
    [
        ("stop", "completed", None),
        ("length", "incomplete", "max_output_tokens"),
        ("max_tokens", "incomplete", "max_output_tokens"),
        ("content_filter", "incomplete", "content_filter"),
    ],
)
def test_native_responses_reports_incomplete_output(
    mode, finish_reason, expected_status, incomplete_reason
):
    app, _ = _make_app(finish_reason=finish_reason)

    response = TestClient(app).post(
        f"/{mode}/responses", json={"model": "GigaChat-2-Max", "input": "hello"}
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["incomplete_details"] == (
        {"reason": incomplete_reason} if incomplete_reason else None
    )
    assert payload["output"][0]["content"][0]["text"] == "partial text"


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("stream", [False, True])
def test_native_responses_rejects_unresolved_tool_result_name_before_upstream(
    mode, stream
):
    app, upstream = _make_app()
    payload = {
        "model": "GigaChat-2-Max",
        "stream": stream,
        "input": [
            {
                "type": "function_call_output",
                "call_id": "call_lookup",
                "output": '{"value": 42}',
            }
        ],
    }
    if mode == "v2":
        payload["previous_response_id"] = "resp_thread-1"

    response = TestClient(app).post(f"/{mode}/responses", json=payload)

    assert response.status_code == 400, response.text
    assert response.json()["error"]["param"] == "input[0].name"
    assert response.json()["error"]["code"] == "unsupported_semantic"
    assert not upstream.payloads


@pytest.mark.parametrize("mode", ["v1", "v2"])
@pytest.mark.parametrize("name_source", ["result", "history"])
def test_native_responses_preserves_tool_result_with_resolved_name(mode, name_source):
    app, upstream = _make_app()
    output = {
        "type": "function_call_output",
        "call_id": "call_lookup",
        "output": '{"value": 42}',
    }
    history = []
    if name_source == "result":
        output["name"] = "lookup"
    else:
        history.append(
            {
                "type": "function_call",
                "call_id": "call_lookup",
                "name": "lookup",
                "arguments": "{}",
            }
        )
    payload = {"model": "GigaChat-2-Max", "input": [*history, output]}
    if mode == "v2" and name_source == "result":
        payload["previous_response_id"] = "resp_thread-1"

    response = TestClient(app).post(f"/{mode}/responses", json=payload)

    assert response.status_code == 200, response.text
    prepared = upstream.payloads[0]
    if mode == "v2":
        result = prepared.messages[-1].content[0].function_result
        assert result.id_ == "call_lookup"
        assert result.name == "lookup"
        assert result.result == {"value": 42}
    else:
        result = prepared["messages"][-1]
        assert result["name"] == "lookup"
        assert result["content"] == '{"value": 42}'
