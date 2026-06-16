import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.routers.openai import router
import gpt2giga.routers.openai.chat_completions as chat_module


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
    def __init__(self):
        self.chat_calls = []
        self.response_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append((data, giga_client))
        return {"model": data.get("model", "giga")}

    async def prepare_response_chat(self, data, giga_client=None):
        self.response_calls.append((data, giga_client))
        return {"model": data.get("model", "giga")}


class RecordingObservabilitySink:
    def __init__(self):
        self.events = []

    async def emit(self, name, attributes=None, *, context=None, events=None):
        self.events.append((name, attributes or {}, context, list(events or [])))

    async def flush(self):
        return None


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
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


def test_chat_completions_legacy_strips_assistant_function_state_id():
    class RecordingGigachat(FakeGigachat):
        def __init__(self):
            self.chat_calls = []

        async def achat(self, chat):
            self.chat_calls.append(chat)
            return await super().achat(chat)

    state_id = "019ed0fe-194e-7e50-87b1-16acc2509040"
    app = make_app_with_real_transformer()
    app.state.gigachat_client = RecordingGigachat()
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        json={
            "model": "GigaChat-2-Max",
            "messages": [
                {"role": "user", "content": "Какая погода в Москве?"},
                {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": "get_weather",
                        "arguments": {"city": "Москва"},
                    },
                    "functions_state_id": state_id,
                },
                {
                    "role": "function",
                    "content": (
                        '{"city": "Москва", "temp": "+5°C", "conditions": "облачно"}'
                    ),
                    "name": "get_weather",
                    "functions_state_id": state_id,
                },
            ],
            "functions": [
                {
                    "name": "get_weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    sent_messages = app.state.gigachat_client.chat_calls[0]["messages"]
    assert "functions_state_id" not in sent_messages[1]
    assert sent_messages[2]["functions_state_id"] == state_id


def test_chat_completions_legacy_non_stream_emits_phoenix_input_output_span():
    class FakeGigachatWithHeaders(FakeGigachat):
        async def achat(self, chat):
            response = await super().achat(chat)
            response.data["choices"][0]["message"]["reasoning_content"] = (
                "hidden reasoning"
            )
            response.data["x_headers"] = {
                "x-request-id": "rq-1",
                "x-session-id": "session-1",
            }
            return response

    app = make_app()
    app.state.gigachat_client = FakeGigachatWithHeaders()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode="v1",
            observability_capture_content=True,
            observability_capture_messages=True,
            observability_capture_responses=True,
        )
    )
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "secret prompt"}],
        },
    )

    assert response.status_code == 200
    emitted = {
        name: attributes
        for name, attributes, _context, _events in app.state.observability_sink.events
    }
    attributes = emitted["OpenAI-Completions"]
    assert attributes["gpt2giga.api_format"] == "chat_completions"
    assert "secret prompt" in attributes["input.value"]
    assert "ok" in attributes["output.value"]
    assert "hidden reasoning" in attributes["output.value"]
    assert "reasoning_content" in attributes["output.value"]
    assert attributes["llm.response.metadata"] == (
        '{"gigachat_x_request_id": "rq-1", "gigachat_x_session_id": "session-1"}'
    )


def test_chat_completions_legacy_stream_emits_phoenix_input_output_span():
    class FakeGigachatStreamingWithHeaders(FakeGigachat):
        def astream(self, chat):
            async def gen():
                yield MockResponse(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "role": "assistant",
                                    "content": "Hel",
                                },
                                "finish_reason": None,
                            }
                        ],
                        "usage": None,
                        "x_headers": {"x-request-id": "rq-stream"},
                    }
                )
                yield MockResponse(
                    {
                        "choices": [
                            {
                                "delta": {"content": "lo"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 2,
                            "completion_tokens": 3,
                            "total_tokens": 5,
                        },
                        "x_headers": {"x-session-id": "session-stream"},
                    }
                )

            return gen()

    app = make_app()
    app.state.gigachat_client = FakeGigachatStreamingWithHeaders()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode="v1",
            observability_capture_content=True,
            observability_capture_messages=True,
            observability_capture_responses=True,
        )
    )
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "secret prompt"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    emitted = {
        name: attributes
        for name, attributes, _context, _events in app.state.observability_sink.events
    }
    attributes = emitted["OpenAI-Completions"]

    assert response.status_code == 200
    assert attributes["gpt2giga.api_format"] == "chat_completions"
    assert "data: [DONE]" in body
    assert "secret prompt" in attributes["input.value"]
    assert "Hello" in attributes["output.value"]
    assert attributes["llm.finish_reason"] == "stop"
    assert attributes["llm.token_count.total"] == 5
    assert attributes["llm.response.metadata"] == (
        '{"gigachat_x_request_id": "rq-stream", '
        '"gigachat_x_session_id": "session-stream"}'
    )


def test_chat_completions_normalization_on_uses_non_stream_normalized_path():
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            normalization_mode="on",
            gigachat_api_mode="v1",
            observability_capture_content=False,
            observability_capture_messages=False,
            observability_capture_tool_args=False,
            observability_capture_responses=False,
        )
    )
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]},
    )

    body = resp.json()
    assert resp.status_code == 200
    assert body["object"] == "chat.completion"
    assert body["model"] == "gpt-x"
    assert body["choices"][0]["message"]["content"] == "ok"
    assert app.state.request_transformer.chat_calls


def test_chat_completions_normalization_on_emits_safe_llm_observability_spans():
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            normalization_mode="on",
            gigachat_api_mode="v1",
            observability_capture_content=False,
            observability_capture_messages=False,
            observability_capture_tool_args=False,
            observability_capture_responses=False,
        )
    )
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "secret prompt"}],
        },
    )

    assert response.status_code == 200
    emitted = {
        name: attributes
        for name, attributes, _context, _events in app.state.observability_sink.events
    }
    assert list(emitted) == ["OpenAI-Completions"]
    assert emitted["OpenAI-Completions"]["gpt2giga.api_format"] == "chat_completions"
    assert emitted["OpenAI-Completions"]["llm.input_messages.count"] == 1
    assert emitted["OpenAI-Completions"]["llm.finish_reason"] == "tool_calls"
    assert "secret prompt" not in json.dumps(emitted)


def test_chat_completions_normalization_on_uses_streaming_normalized_path():
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(normalization_mode="on", gigachat_api_mode="v1")
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "chat.completion.chunk" in body
    assert "data: [DONE]" in body
    assert app.state.request_transformer.chat_calls


def test_chat_completions_normalization_on_emits_stream_span_events():
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            normalization_mode="on",
            gigachat_api_mode="v1",
            observability_capture_content=True,
            observability_capture_messages=True,
            observability_capture_responses=True,
        )
    )
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    event_names = [
        event["name"]
        for name, _attributes, _context, events in app.state.observability_sink.events
        if name == "OpenAI-Completions"
        for event in events
    ]
    emitted = {
        name: attributes
        for name, attributes, _context, _events in app.state.observability_sink.events
    }

    assert response.status_code == 200
    assert "data: [DONE]" in body
    assert "stream.start" in event_names
    assert "stream.completed" in event_names
    assert "stream.emit" not in emitted
    assert "OpenAI-Completions" in emitted
    assert emitted["OpenAI-Completions"]["gpt2giga.api_format"] == "chat_completions"
    assert "hi" in emitted["OpenAI-Completions"]["input.value"]


def test_chat_completions_stream_span_event_failure_does_not_break_sse(monkeypatch):
    def fail_stream_span_events(*args, **kwargs):
        raise RuntimeError("span event failed")

    monkeypatch.setattr(
        chat_module, "build_stream_span_events", fail_stream_span_events
    )
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            normalization_mode="on",
            gigachat_api_mode="v1",
            observability_capture_content=True,
            observability_capture_messages=True,
            observability_capture_responses=True,
        )
    )
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    emitted = {
        name: attributes
        for name, attributes, _context, _events in app.state.observability_sink.events
    }

    assert response.status_code == 200
    assert "data: [DONE]" in body
    assert "OpenAI-Completions" in emitted


def test_chat_completions_normalization_on_stream_falls_back_before_sse_start():
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            normalization_mode="on",
            legacy_chat_fallback=True,
            gigachat_api_mode="v1",
        )
    )

    class BrokenAdapter:
        async def to_normalized(self, payload, *, context=None):
            raise RuntimeError("normalized failed")

    app.state.openai_protocol_adapter = BrokenAdapter()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "data: [DONE]" in body
    assert app.state.request_transformer.chat_calls


def test_chat_completions_normalization_on_falls_back_to_legacy_when_enabled():
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            normalization_mode="on",
            legacy_chat_fallback=True,
            gigachat_api_mode="v1",
        )
    )

    class BrokenAdapter:
        async def to_normalized(self, payload, *, context=None):
            raise RuntimeError("normalized failed")

    app.state.openai_protocol_adapter = BrokenAdapter()
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    assert resp.json()["object"] == "chat.completion"
    assert app.state.request_transformer.chat_calls


def test_chat_completions_normalization_on_without_fallback_returns_error():
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            normalization_mode="on",
            legacy_chat_fallback=False,
            gigachat_api_mode="v1",
        )
    )

    class BrokenAdapter:
        async def to_normalized(self, payload, *, context=None):
            raise RuntimeError("normalized failed")

    app.state.openai_protocol_adapter = BrokenAdapter()
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 500
    assert resp.json()["error"]["type"] == "server_error"


def test_chat_completions_shadow_mode_adapter_error_does_not_break_legacy_response():
    calls = []
    app = make_app()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(normalization_mode="shadow", gigachat_api_mode="v1")
    )

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
    app.state.config = ProxyConfig(
        proxy=ProxySettings(normalization_mode="off", gigachat_api_mode="v1")
    )

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
    app.state.config = ProxyConfig(
        proxy=ProxySettings(normalization_mode="shadow", gigachat_api_mode="v1")
    )
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


def test_chat_completions_ignores_unsupported_param():
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "logprobs": True,
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "ok"


def test_chat_completions_ignores_malformed_tools():
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": "bad",
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "ok"


@pytest.mark.parametrize(
    "tool_payload",
    [
        {"functions": [{"parameters": {"type": "object", "properties": {}}}]},
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
            }
        ),
    ],
)
def test_chat_completions_ignores_tool_definitions_without_name(tool_payload):
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        **tool_payload,
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "ok"


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
