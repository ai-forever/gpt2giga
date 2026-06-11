import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionChunk
from gigachat.models.chat_completions import ChatCompletionResponse
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.openai import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeAChatResource:
    def __init__(self):
        self.v1_calls = []
        self.v2_calls = []
        self.stream_calls = []
        self.thread_id = None

    async def __call__(self, payload):
        self.v1_calls.append(payload)
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok-v1"},
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

    async def create(self, payload):
        self.v2_calls.append(payload)
        response_payload = {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"text": "ok-v2"}],
                }
            ],
            "finish_reason": "stop",
            "usage": {
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
            },
        }
        if self.thread_id is not None:
            response_payload["thread_id"] = self.thread_id
        return ChatCompletionResponse.model_validate(response_payload)

    def stream(self, payload):
        self.stream_calls.append(payload)

        async def gen():
            chunk_payload = {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"text": "ok-stream"}],
                    }
                ]
            }
            if self.thread_id is not None:
                chunk_payload["thread_id"] = self.thread_id
            yield ChatCompletionChunk.model_validate(chunk_payload)

        return gen()


class FakeGigachat:
    def __init__(self):
        self.achat = FakeAChatResource()


class FakeRequestTransformer:
    def __init__(self):
        self.v1_calls = []
        self.v2_calls = []

    async def prepare_chat_completion(self, data, giga_client=None):
        return {"contract": "chat-v1"}

    async def prepare_response(self, data, giga_client=None):
        self.v1_calls.append((data, giga_client))
        return {"contract": "responses-v1"}

    async def prepare_response_v2(self, data, giga_client=None):
        self.v2_calls.append((data, giga_client))
        return {"contract": "responses-v2"}


class RecordingObservabilitySink:
    def __init__(self):
        self.events = []

    async def emit(self, name, attributes=None, *, context=None, events=None):
        self.events.append((name, attributes or {}, context, list(events or [])))

    async def flush(self):
        return None


def make_app(gigachat_api_mode: str, responses_api_mode: str):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode=gigachat_api_mode,
            responses_api_mode=responses_api_mode,
        ),
    )
    return app


@pytest.mark.parametrize(
    ("gigachat_api_mode", "responses_api_mode", "expected_mode"),
    [
        ("v1", "inherit", "v1"),
        ("v2", "inherit", "v2"),
        ("v1", "v2", "v2"),
        ("v2", "v1", "v1"),
    ],
)
def test_responses_api_mode_matrix(
    gigachat_api_mode,
    responses_api_mode,
    expected_mode,
):
    app = make_app(gigachat_api_mode, responses_api_mode)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
        },
    )

    assert response.status_code == 200
    if expected_mode == "v1":
        assert app.state.request_transformer.v1_calls
        assert not app.state.request_transformer.v2_calls
        assert app.state.gigachat_client.achat.v1_calls == [
            {"contract": "responses-v1"}
        ]
        assert app.state.gigachat_client.achat.v2_calls == []
        assert response.json()["output"][0]["content"][0]["text"] == "ok-v1"
    else:
        assert not app.state.request_transformer.v1_calls
        assert app.state.request_transformer.v2_calls
        assert app.state.gigachat_client.achat.v1_calls == []
        assert app.state.gigachat_client.achat.v2_calls == [
            {"contract": "responses-v2"}
        ]
        assert response.json()["output"][0]["content"][0]["text"] == "ok-v2"


def test_responses_v2_non_stream_returns_openai_response_object():
    app = make_app("v2", "inherit")
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["output"][0]["type"] == "message"
    assert body["output"][0]["content"][0]["text"] == "ok-v2"
    assert body["usage"]["input_tokens"] == 2
    assert body["usage"]["output_tokens"] == 3


def test_responses_v1_non_stream_emits_phoenix_llm_span():
    app = make_app("v1", "inherit")
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode="v1",
            responses_api_mode="inherit",
            observability_capture_content=True,
            observability_capture_messages=True,
            observability_capture_responses=True,
        ),
    )
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
            "tools": [
                {
                    "type": "function",
                    "name": "lookup",
                    "parameters": {"type": "object"},
                }
            ],
        },
    )

    emitted = {
        name: (attributes, events)
        for name, attributes, _context, events in app.state.observability_sink.events
    }
    attributes, events = emitted["Responses"]

    assert response.status_code == 200
    assert attributes["gpt2giga.api_format"] == "responses"
    assert attributes["llm.operation"] == "responses"
    assert attributes["llm.streaming"] is False
    assert attributes["status"] == "ok"
    assert attributes["llm.tools.count"] == 1
    assert attributes["llm.tools.names"] == ["lookup"]
    assert attributes["total_tokens"] == 2
    assert "hi" in attributes["input.value"]
    assert "ok-v1" in attributes["output.value"]
    assert events == []


def test_responses_v2_uses_thread_id_as_response_id():
    app = make_app("v2", "inherit")
    app.state.gigachat_client.achat.thread_id = "thread_1"
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == "resp_thread_1"
    emitted = {
        name: attributes
        for name, attributes, _context, _events in app.state.observability_sink.events
    }
    assert emitted["Responses"]["gpt2giga.api_format"] == "responses"
    assert emitted["Responses"]["session.id"] == "thread_1"
    assert emitted["Responses"]["conversation.id"] == "thread_1"


def test_responses_v2_stream_uses_primary_stream():
    app = make_app("v2", "inherit")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: response.output_text.delta" in body
    assert "ok-stream" in body
    assert not app.state.request_transformer.v1_calls
    assert app.state.request_transformer.v2_calls
    assert app.state.gigachat_client.achat.v1_calls == []
    assert app.state.gigachat_client.achat.v2_calls == []
    assert app.state.gigachat_client.achat.stream_calls == [
        {"contract": "responses-v2"}
    ]


def test_responses_v2_stream_emits_phoenix_llm_span():
    app = make_app("v2", "inherit")
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode="v2",
            responses_api_mode="inherit",
            observability_capture_content=True,
            observability_capture_messages=True,
            observability_capture_responses=True,
        ),
    )
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    emitted = {
        name: (attributes, events)
        for name, attributes, _context, events in app.state.observability_sink.events
    }
    attributes, events = emitted["Responses"]
    event_names = [event["name"] for event in events]

    assert response.status_code == 200
    assert attributes["gpt2giga.api_format"] == "responses"
    assert "event: response.completed" in body
    assert attributes["llm.operation"] == "responses"
    assert attributes["llm.streaming"] is True
    assert attributes["status"] == "ok"
    assert "hi" in attributes["input.value"]
    assert "ok-stream" in attributes["output.value"]
    assert "stream.start" in event_names
    assert "stream.first_token" in event_names
    assert "stream.completed" in event_names


def test_responses_v2_stream_uses_thread_id_as_response_id():
    app = make_app("v2", "inherit")
    app.state.gigachat_client.achat.thread_id = "thread_1"
    app.state.observability_sink = RecordingObservabilitySink()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
            "previous_response_id": "resp_previous",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    completed_event = [
        block for block in body.split("\n\n") if "event: response.completed" in block
    ][-1]
    payload = json.loads(
        next(
            line for line in completed_event.splitlines() if line.startswith("data: ")
        ).removeprefix("data: ")
    )
    assert payload["response"]["id"] == "resp_thread_1"
    assert payload["response"]["previous_response_id"] == "resp_previous"
    emitted = {
        name: attributes
        for name, attributes, _context, _events in app.state.observability_sink.events
    }
    assert emitted["Responses"]["session.id"] == "thread_1"
    assert emitted["Responses"]["conversation.id"] == "thread_1"
