import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
import pytest

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.providers.gigachat.adapter import normalized_chat_to_openai_payload
from gpt2giga.routers.openai.responses import router


class _Response:
    def __init__(self, data=None):
        self.data = data

    def model_dump(self):
        return self.data or {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "normalized"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "total_tokens": 5,
            },
        }


class _GigaChat:
    def __init__(self):
        self.calls = []
        self.stream_calls = []

    async def achat(self, payload):
        self.calls.append(payload)
        return _Response()

    def astream(self, payload):
        self.stream_calls.append(payload)

        async def generate():
            yield _Response(
                {
                    "choices": [{"delta": {"content": "nor"}, "finish_reason": None}],
                    "usage": None,
                }
            )
            yield _Response(
                {
                    "choices": [
                        {"delta": {"content": "malized"}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )

        return generate()


class _Transformer:
    def __init__(self, *, allow_native: bool = False):
        self.chat_calls = []
        self.native_responses_calls = []
        self.allow_native = allow_native

    async def prepare_normalized(self, request, giga_client=None, **kwargs):
        return await self.prepare_chat(
            normalized_chat_to_openai_payload(request), giga_client
        )

    async def prepare_chat(self, data, giga_client=None, **kwargs):
        self.chat_calls.append(data)
        return data

    async def prepare_response_chat(self, data, giga_client=None, **kwargs):
        self.native_responses_calls.append(data)
        if not self.allow_native:
            raise AssertionError("native Responses owner must not run")
        return {"model": data["model"], "messages": []}


def _app() -> tuple[FastAPI, _GigaChat, _Transformer]:
    app = FastAPI()
    app.include_router(router)
    client = _GigaChat()
    transformer = _Transformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v1"),
        gigachat={"model": "GigaChat-2-Max"},
    )
    app.state.gigachat_client = client
    app.state.logger = logger
    limiter = ModelConcurrencyLimiter({})
    app.state.model_concurrency_limiter = limiter
    app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
    app.state.request_transformer = transformer
    response_processor = ResponseProcessor(logger=logger)
    app.state.response_processor = response_processor
    app.state.responses_provider_adapter = GigaChatProviderAdapter(
        config=app.state.config,
        request_transformer=transformer,
        giga_client=client,
        model_limiter=limiter,
        response_processor=response_processor,
        api_mode="v1",
        forced_model="GigaChat-2-Max",
    )
    return app, client, transformer


def test_responses_nonstream_uses_normalized_protocol_and_provider_owners() -> None:
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "instructions": "Be concise.",
            "model": "bridge/codex-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "bridge/codex-test"
    assert response.json()["parallel_tool_calls"] is False
    assert response.json()["output"][0]["content"][0]["text"] == "normalized"
    assert response.json()["usage"] == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }
    assert transformer.native_responses_calls == []
    assert transformer.chat_calls[0]["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "hello"},
    ]
    assert giga_client.calls[0]["model"] == "GigaChat-2-Max"


@pytest.mark.parametrize(
    ("field", "value", "error_param"),
    [
        ("conversation", "fixture", "conversation"),
        ("previous_response_id", "fixture", "previous_response_id"),
        ("reasoning", {"effort": "high"}, "reasoning"),
        ("reasoning_effort", "high", "reasoning"),
    ],
)
def test_responses_normalized_rejects_state_and_reasoning_before_provider_io(
    field: str,
    value: object,
    error_param: str,
) -> None:
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            field: value,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "unsupported_semantic",
        "message": "The selected bridge route cannot preserve this semantic.",
        "param": error_param,
        "type": "invalid_request_error",
    }
    assert transformer.chat_calls == []
    assert transformer.native_responses_calls == []
    assert giga_client.calls == []


def test_responses_normalized_accepts_reasoning_none_as_disabled() -> None:
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            "reasoning": {"effort": "none", "summary": "auto"},
        },
    )

    assert response.status_code == 200
    assert len(transformer.chat_calls) == 1
    assert len(giga_client.calls) == 1


def test_responses_native_path_requires_no_workaround_flag() -> None:
    app, giga_client, _transformer = _app()
    native_transformer = _Transformer(allow_native=True)
    app.state.request_transformer = native_transformer
    del app.state.responses_provider_adapter

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            "reasoning": {"effort": "high"},
        },
    )

    assert response.status_code == 200
    assert len(native_transformer.native_responses_calls) == 1
    assert native_transformer.chat_calls == []
    assert len(giga_client.calls) == 1


def test_responses_defaults_to_normalized_without_startup_adapter() -> None:
    app, giga_client, transformer = _app()
    del app.state.openai_protocol_adapter

    response = TestClient(app).post(
        "/responses",
        json={"input": "hello", "model": "bridge/codex-test"},
    )

    assert response.status_code == 200
    assert transformer.native_responses_calls == []
    assert len(giga_client.calls) == 1


def test_responses_stream_uses_normalized_events_without_native_fallback() -> None:
    app, giga_client, transformer = _app()

    with TestClient(app).stream(
        "POST",
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert [
        block.splitlines()[0]
        for block in body.split("\n\n")
        if block.startswith("event: ")
    ] == [
        "event: response.created",
        "event: response.output_item.added",
        "event: response.content_part.added",
        "event: response.output_text.delta",
        "event: response.output_text.delta",
        "event: response.output_text.done",
        "event: response.content_part.done",
        "event: response.output_item.done",
        "event: response.completed",
    ]
    assert '"text": "normalized"' in body
    assert '"total_tokens": 5' in body
    responses = [
        event["response"]
        for line in body.splitlines()
        if line.startswith("data: ")
        and "response" in (event := json.loads(line.removeprefix("data: ")))
    ]
    assert len(responses) == 2
    assert all(response["parallel_tool_calls"] is False for response in responses)
    assert transformer.native_responses_calls == []
    assert giga_client.calls == []
    assert len(giga_client.stream_calls) == 1


async def _executor_response(app):
    from fastapi import Request
    from gpt2giga.app.responses_execution import NormalizedBridgeResponsesExecutor

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/responses",
            "scheme": "http",
            "server": ("gateway.test", 80),
            "headers": [],
            "query_string": b"",
            "app": app,
        },
        receive=receive,
    )
    return await NormalizedBridgeResponsesExecutor()._stream_response(
        request,
        {"input": "hello", "model": "bridge/codex-test", "stream": True},
        protocol_adapter=OpenAIProtocolAdapter(),
    )


async def test_normalized_executor_close_closes_retained_provider_iterator(monkeypatch):
    from types import SimpleNamespace
    from gpt2giga.protocols.normalized import NormalizedStreamEvent
    import gpt2giga.app.responses_execution as execution

    closed, committed = [], []

    async def provider_stream():
        try:
            yield NormalizedStreamEvent(type="message_start", sequence=0)
            yield NormalizedStreamEvent(
                type="message_end", sequence=1, finish_reason="stop"
            )
        finally:
            closed.append(True)

    async def commit(*args):
        committed.append(True)

    retained = provider_stream()
    app, _, _ = _app()
    app.state.responses_provider_adapter = SimpleNamespace(
        name="external", stream_chat=lambda *args, **kwargs: retained
    )
    monkeypatch.setattr(execution, "commit_responses_response", commit)
    response = await _executor_response(app)
    assert "response.created" in await anext(response.body_iterator)
    await response.body_iterator.aclose()
    assert closed == [True]
    assert committed == []


@pytest.mark.parametrize("commit_failure", [False, True])
async def test_normalized_stream_commits_structured_result_before_terminal(
    monkeypatch, commit_failure
):
    import gpt2giga.app.responses_execution as execution
    from gpt2giga.sinks.observability.responses import OpenAIResponseStreamObserver

    commits, parsed, spans = [], [], []

    class Sink:
        async def emit(self, name, attributes=None, **kwargs):
            spans.append(attributes)

    async def commit(request, turn, result):
        assert result["status"] == "completed"
        assert result["output"][0]["content"][0]["text"] == "normalized"
        if commit_failure:
            raise RuntimeError("synthetic storage failure")
        commits.append(result)

    monkeypatch.setattr(execution, "commit_responses_response", commit)
    monkeypatch.setattr(
        OpenAIResponseStreamObserver,
        "observe_chunk",
        lambda self, chunk: parsed.append(chunk),
    )
    app, _, _ = _app()
    app.state.observability_sink = Sink()
    response = await _executor_response(app)
    frames = []
    async for frame in response.body_iterator:
        if "event: response.completed" in frame:
            assert len(commits) == 1
        frames.append(frame)
    body = "".join(frames)
    assert parsed == []
    assert bool(commits) is not commit_failure
    assert ("event: response.completed" in body) is not commit_failure
    assert body.count("event: error") == int(commit_failure)
    if commit_failure:
        assert "response_storage_error" in body
        assert "synthetic storage failure" not in body
    assert len(spans) == 1
    assert spans[0]["status"] == ("failed" if commit_failure else "ok")


async def test_normalized_stream_observer_failure_does_not_interrupt_response(
    monkeypatch,
):
    from gpt2giga.sinks.observability.responses import OpenAIResponseStreamObserver

    def broken_observer(*args):
        raise RuntimeError("synthetic diagnostics failure")

    monkeypatch.setattr(
        OpenAIResponseStreamObserver, "observe_payload", broken_observer
    )
    app, _, _ = _app()
    response = await _executor_response(app)
    body = "".join([frame async for frame in response.body_iterator])
    assert body.count("event: response.completed") == 1
    assert "event: error" not in body
