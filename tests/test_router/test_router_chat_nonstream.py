import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
import pytest

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.routers.openai import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeGigachat:
    async def achat(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "function_call",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )

    def astream(self, chat):
        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            )

        return gen()


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}

    async def prepare_response(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1"))
    return app


def make_app_with_real_transformer():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.config = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1"))
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
    return app


def test_chat_completions_non_stream_basic():
    app = make_app()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
    }
    resp = client.post("/chat/completions", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"


def test_chat_completions_shadow_mode_adapter_error_does_not_break_legacy_response():
    calls = []
    app = make_app()
    app.state.config = ProxyConfig(proxy=ProxySettings(normalization_mode="shadow"))

    class BrokenShadowAdapter:
        async def to_normalized(self, payload, *, context=None):
            calls.append((payload, context))
            raise RuntimeError("shadow failed")

    app.state.openai_protocol_adapter = BrokenShadowAdapter()
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    assert resp.json()["object"] == "chat.completion"
    assert len(calls) == 1
    event = app.state.normalization_shadow_events[-1]
    assert event.normalization_status == "error"
    assert event.errors == ["RuntimeError"]


def test_chat_completions_normalization_off_does_not_call_shadow_adapter():
    calls = []
    app = make_app()
    app.state.config = ProxyConfig(proxy=ProxySettings(normalization_mode="off"))

    class RecordingShadowAdapter:
        async def to_normalized(self, payload, *, context=None):
            calls.append(payload)

    app.state.openai_protocol_adapter = RecordingShadowAdapter()
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    assert calls == []


def test_chat_completions_shadow_mode_records_shape_diagnostic_without_raw_prompt():
    app = make_app()
    app.state.config = ProxyConfig(proxy=ProxySettings(normalization_mode="shadow"))
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "secret prompt"}],
        },
    )

    assert resp.status_code == 200
    event = app.state.normalization_shadow_events[-1]
    payload = event.to_json_dict()
    assert payload["normalization_status"] == "ok"
    assert payload["normalized_shape_hash"].startswith("sha256:")
    assert "secret prompt" not in json.dumps(payload)


def test_chat_completions_v1_non_stream_preserves_called_tools_from_request():
    app = make_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_call": {
                                "name": "run_shell_command",
                                "arguments": {"command": "make install"},
                            }
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_result": {
                                "name": "run_shell_command",
                                "result": {"result": "ok"},
                            }
                        }
                    ],
                },
            ],
        },
    )

    metadata = resp.json()["metadata"]
    assert resp.status_code == 200
    assert json.loads(metadata["gigachat_called_tools"]) == [
        {
            "index": 0,
            "message_index": 0,
            "name": "run_shell_command",
            "arguments": {"command": "make install"},
            "content_index": 0,
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]


def test_chat_completions_v1_stream_preserves_called_tools_from_request():
    app = make_app()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_call": {
                                "name": "run_shell_command",
                                "arguments": {"command": "make install"},
                            }
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_result": {
                                "name": "run_shell_command",
                                "result": {"result": "ok"},
                            }
                        }
                    ],
                },
            ],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: {")
    ]
    metadata = chunks[-1]["metadata"]

    assert response.status_code == 200
    assert json.loads(metadata["gigachat_called_tools"]) == [
        {
            "index": 0,
            "message_index": 0,
            "name": "run_shell_command",
            "arguments": {"command": "make install"},
            "content_index": 0,
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]


def test_chat_completions_rejects_unsupported_param_with_openai_error():
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "logprobs": True,
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == "logprobs"


def test_chat_completions_rejects_malformed_tools_with_openai_error():
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": "bad",
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == "tools"


@pytest.mark.parametrize(
    ("tool_payload", "param"),
    [
        (
            {"functions": [{"parameters": {"type": "object", "properties": {}}}]},
            "functions",
        ),
        (
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "parameters": {"type": "object", "properties": {}}
                        },
                    }
                ]
            },
            "tools",
        ),
    ],
)
def test_chat_completions_rejects_tool_definitions_without_name(tool_payload, param):
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        **tool_payload,
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == param


def test_chat_completions_non_stream_response_api():
    app = make_app()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "input": "hi",
    }
    resp = client.post("/chat/completions", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
