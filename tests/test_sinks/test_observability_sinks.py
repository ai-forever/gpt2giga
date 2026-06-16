import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from gpt2giga.core.context import RequestContext
from gpt2giga.core.interfaces import ObservabilitySink
from gpt2giga.models.config import ProxySettings
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedTool,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.sinks.observability.factory import (
    create_observability_sink,
    emit_observability_event,
    flush_observability_sink,
)
from gpt2giga.sinks.observability.llm import (
    build_llm_request_attributes,
    build_llm_response_attributes,
    build_stream_span_events,
    build_tool_call_span_events,
)
from gpt2giga.sinks.observability.noop import NoopObservabilitySink
from gpt2giga.sinks.observability.otel import (
    OpenTelemetryObservabilitySink,
    build_otel_attributes,
)
from gpt2giga.sinks.observability.responses import (
    OpenAIResponseStreamObserver,
    emit_openai_response_observability,
)


def capture_off_settings() -> ProxySettings:
    return ProxySettings(
        observability_capture_content=False,
        observability_capture_messages=False,
        observability_capture_tool_args=False,
        observability_capture_responses=False,
    )


def assert_span_status_code(status: object, expected: str) -> None:
    status_code = getattr(status, "status_code", status)
    status_name = getattr(status_code, "name", None)
    assert (status_name or str(status_code)) == expected


async def test_noop_observability_sink_implements_contract():
    sink = NoopObservabilitySink()

    assert isinstance(sink, ObservabilitySink)
    await sink.emit("request.completed", {"status_code": 200})
    await sink.flush()


def test_observability_factory_returns_noop_when_enabled():
    sink = create_observability_sink(ProxySettings(observability_enabled=False))

    assert isinstance(sink, NoopObservabilitySink)


def test_observability_factory_returns_phoenix_sink(monkeypatch):
    class FakeSink:
        async def emit(self, name, attributes=None, *, context=None):
            return None

        async def flush(self):
            return None

    fake_sink = FakeSink()
    monkeypatch.setattr(
        "gpt2giga.sinks.observability.factory.create_phoenix_observability_sink",
        lambda settings: fake_sink,
    )

    sink = create_observability_sink(ProxySettings(observability_enabled=True))

    assert sink is fake_sink


def test_observability_factory_falls_back_to_noop_when_phoenix_unavailable(
    monkeypatch,
):
    def fail(settings):
        raise ImportError("missing optional dependency")

    monkeypatch.setattr(
        "gpt2giga.sinks.observability.factory.create_phoenix_observability_sink",
        fail,
    )

    sink = create_observability_sink(ProxySettings(observability_enabled=True))

    assert isinstance(sink, NoopObservabilitySink)


def test_build_otel_attributes_adds_context_redacts_and_drops_content():
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id="span-1",
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
        caller_name="codex",
        caller_category="agent",
        caller_client_family="openai",
        caller_agent="codex",
        caller_user_agent="codex-cli/0.1",
        annotations={"caller": {"name": "codex", "category": "agent"}},
        model_requested="GigaChat",
    )

    attributes = build_otel_attributes(
        {
            "status_code": 200,
            "authorization": "Bearer secret-token",
            "request_body": {"messages": [{"content": "raw prompt"}]},
            "metadata": {"nested": True},
        },
        context=context,
    )

    assert attributes["request_id"] == "req-1"
    assert attributes["trace_id"] == "trace-1"
    assert attributes["route"] == "/v1/chat/completions"
    assert attributes["caller.name"] == "codex"
    assert attributes["caller.agent"] == "codex"
    assert attributes["caller.client_family"] == "openai"
    assert attributes["annotations"] == (
        '{"caller": {"category": "agent", "name": "codex"}}'
    )
    assert attributes["status_code"] == 200
    assert attributes["authorization"] == "***"
    assert "request_body" not in attributes
    assert attributes["metadata"] == '{"nested": true}'


def test_build_otel_attributes_maps_conversation_metadata_for_phoenix_sessions():
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id="span-1",
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        started_at=datetime.now(timezone.utc),
        metadata={
            "conversation_id": "conv-1",
            "conversation_save_id": "conv-1",
            "conversation_stitched": True,
            "conversation_history_messages": 2,
            "conversation_revision": 1,
            "conversation_saved_messages": 4,
            "conversation_saved_revision": 2,
        },
    )

    attributes = build_otel_attributes({}, context=context)

    assert attributes["session.id"] == "conv-1"
    assert attributes["conversation.id"] == "conv-1"
    assert attributes["conversation.save_id"] == "conv-1"
    assert attributes["conversation.stitched"] is True
    assert attributes["conversation.history_messages"] == 2
    assert attributes["conversation.revision"] == 1
    assert attributes["conversation.saved_messages"] == 4
    assert attributes["conversation.saved_revision"] == 2


def test_build_llm_request_attributes_default_omits_raw_content():
    request = NormalizedChatRequest(
        model="GigaChat",
        messages=[
            NormalizedMessage(role="user", content="secret prompt"),
            NormalizedMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    NormalizedToolCall(
                        id="call-1",
                        name="search",
                        arguments='{"api_key":"secret"}',
                    )
                ],
            ),
        ],
        tools=[
            NormalizedTool(
                name="search",
                parameters={"type": "object", "properties": {"query": {}}},
            )
        ],
        generation_config=NormalizedGenerationConfig(temperature=0.2),
    )

    attributes = build_llm_request_attributes(request, settings=capture_off_settings())
    serialized = str(attributes)

    assert attributes["openinference.span.kind"] == "LLM"
    assert attributes["llm.model_name"] == "GigaChat"
    assert attributes["llm.input_messages.count"] == 2
    assert attributes["llm.tools.count"] == 1
    assert attributes["llm.tools.names"] == ["search"]
    assert "secret prompt" not in serialized
    assert "api_key" not in serialized
    assert "llm.input_messages" not in attributes
    assert "llm.tools" not in attributes


def test_build_llm_request_attributes_exposes_redacted_request_extensions():
    request = NormalizedChatRequest(
        protocol="gemini",
        model="GigaChat",
        messages=[NormalizedMessage(role="user", content="hello")],
        generation_config=NormalizedGenerationConfig(
            raw_extensions={
                "candidateCount": 2,
                "topK": 40,
                "responseModalities": ["TEXT"],
            }
        ),
        raw_extensions={
            "safetySettings": [{"category": "HARM_CATEGORY_HARASSMENT"}],
            "cachedContent": "cachedContents/1",
            "serviceTier": "flex",
            "unsupportedTools": [{"googleSearch": {"api_key": "secret-gemini-key"}}],
        },
    )

    attributes = build_llm_request_attributes(request, settings=capture_off_settings())

    extensions = json.loads(attributes["llm.request.extensions"])
    invocation = json.loads(attributes["llm.invocation_parameters"])

    assert extensions["safetySettings"] == [{"category": "HARM_CATEGORY_HARASSMENT"}]
    assert extensions["cachedContent"] == "cachedContents/1"
    assert extensions["serviceTier"] == "flex"
    assert extensions["unsupportedTools"] == [{"googleSearch": {"api_key": "***"}}]
    assert invocation["raw_extensions"] == {
        "candidateCount": 2,
        "topK": 40,
        "responseModalities": ["TEXT"],
    }
    assert "secret-gemini-key" not in attributes["llm.request.extensions"]


def test_build_llm_request_attributes_includes_mcp_tool_names_from_extensions():
    request = NormalizedChatRequest(
        model="GigaChat",
        messages=[
            NormalizedMessage(
                role="user",
                content="secret prompt",
                raw_extensions={
                    "additional_kwargs": {
                        "mcp_tools": [
                            {
                                "name": "bitrix-search",
                                "description": "Search Bitrix docs",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {"query": {"type": "string"}},
                                },
                            }
                        ]
                    }
                },
            )
        ],
    )

    attributes = build_llm_request_attributes(request, settings=capture_off_settings())

    assert attributes["llm.tools.count"] == 1
    assert attributes["llm.tools.names"] == ["bitrix-search"]
    assert "secret prompt" not in str(attributes)
    assert "llm.tools" not in attributes


def test_build_llm_request_attributes_respects_capture_redaction_and_limit():
    request = NormalizedChatRequest(
        model="GigaChat",
        messages=[
            NormalizedMessage(
                role="user",
                content="hello " + ("x" * 100),
            )
        ],
        tools=[
            NormalizedTool(
                name="lookup",
                parameters={"type": "object", "api_key": "secret-value"},
            )
        ],
    )
    settings = ProxySettings(
        observability_capture_content=True,
        observability_capture_messages=True,
        observability_capture_tool_args=True,
        observability_max_content_length=64,
    )

    attributes = build_llm_request_attributes(request, settings=settings)

    assert attributes["llm.input_messages"].endswith("...[truncated]")
    assert len(attributes["llm.input_messages"]) == 64

    untruncated_attributes = build_llm_request_attributes(
        request,
        settings=ProxySettings(
            observability_capture_content=True,
            observability_capture_tool_args=True,
            observability_max_content_length=512,
        ),
    )
    assert '"api_key": "***"' in untruncated_attributes["llm.tools"]
    assert "secret-value" not in untruncated_attributes["llm.tools"]


def test_build_llm_response_attributes_maps_usage_finish_and_safe_payloads():
    response = NormalizedResponse(
        model="GigaChat",
        provider="gigachat",
        metadata={"gigachat_x_request_id": "rq-1"},
        choices=[
            NormalizedChoice(
                finish_reason="tool_calls",
                message=NormalizedMessage(
                    role="assistant",
                    content="private answer",
                    raw_extensions={"reasoning_content": "private reasoning"},
                    tool_calls=[
                        NormalizedToolCall(
                            name="lookup",
                            arguments={"password": "secret"},
                        )
                    ],
                ),
            )
        ],
        usage=NormalizedUsage(input_tokens=3, output_tokens=5, total_tokens=8),
    )
    default_attributes = build_llm_response_attributes(
        response,
        settings=capture_off_settings(),
    )

    assert default_attributes["llm.finish_reason"] == "tool_calls"
    assert default_attributes["status"] == "ok"
    assert default_attributes["llm.response.status"] == "ok"
    assert default_attributes["llm.response.metadata"] == (
        '{"gigachat_x_request_id": "rq-1"}'
    )
    assert default_attributes["llm.token_count.prompt"] == 3
    assert default_attributes["llm.token_count.completion"] == 5
    assert default_attributes["llm.token_count.total"] == 8
    assert default_attributes["input_tokens"] == 3
    assert default_attributes["output_tokens"] == 5
    assert default_attributes["total_tokens"] == 8
    assert default_attributes["llm.tool_calls.names"] == ["lookup"]
    assert "private answer" not in str(default_attributes)
    assert "private reasoning" not in str(default_attributes)
    assert "llm.output_messages" not in default_attributes
    assert "llm.tool_calls" not in default_attributes

    captured_attributes = build_llm_response_attributes(
        response,
        settings=ProxySettings(
            observability_capture_content=True,
            observability_capture_responses=True,
            observability_capture_tool_args=True,
        ),
    )

    assert "private answer" in captured_attributes["llm.output_messages"]
    assert "private reasoning" in captured_attributes["llm.output_messages"]
    assert "reasoning_content" in captured_attributes["llm.output_messages"]
    assert '"password": "***"' in captured_attributes["llm.tool_calls"]
    assert "secret" not in captured_attributes["llm.tool_calls"]


def test_build_llm_response_attributes_maps_called_tools_metadata_safely():
    response = NormalizedResponse(
        model="GigaChat",
        provider="gigachat",
        metadata={
            "gigachat_called_tools": json.dumps(
                [
                    {
                        "name": "shell",
                        "arguments": {"password": "secret"},
                        "status": "ok",
                    }
                ]
            )
        },
        usage=NormalizedUsage(input_tokens=7, output_tokens=11, total_tokens=18),
    )

    default_attributes = build_llm_response_attributes(
        response,
        settings=capture_off_settings(),
    )
    default_events = build_tool_call_span_events(
        response,
        settings=capture_off_settings(),
    )

    assert default_attributes["llm.tool_calls.count"] == 1
    assert default_attributes["llm.tool_calls.names"] == ["shell"]
    assert default_attributes["total_tokens"] == 18
    assert "password" not in default_attributes["llm.response.metadata"]
    assert "secret" not in json.dumps(default_attributes)
    assert default_events[0]["name"] == "llm.tool_call"
    assert default_events[0]["attributes"]["llm.tool_call.name"] == "shell"
    assert "llm.tool_calls" not in default_events[0]["attributes"]

    captured_attributes = build_llm_response_attributes(
        response,
        settings=ProxySettings(
            observability_capture_content=True,
            observability_capture_tool_args=True,
        ),
    )
    captured_events = build_tool_call_span_events(
        response,
        settings=ProxySettings(
            observability_capture_content=True,
            observability_capture_tool_args=True,
        ),
    )

    assert '"password": "***"' in captured_attributes["llm.tool_calls"]
    assert "secret" not in captured_attributes["llm.tool_calls"]
    assert '"password": "***"' in captured_attributes["llm.response.metadata"]
    assert "secret" not in captured_attributes["llm.response.metadata"]
    assert '"password": "***"' in captured_events[0]["attributes"]["llm.tool_calls"]


def test_build_stream_span_events_maps_safe_events_and_capture_policy():
    content_event = NormalizedStreamEvent(
        type="content_delta",
        model="GigaChat",
        sequence=1,
        content_delta="secret answer",
    )
    default_events = build_stream_span_events(
        content_event,
        settings=capture_off_settings(),
        first_content_delta=True,
    )

    assert default_events[0]["name"] == "stream.first_token"
    assert "secret answer" not in str(default_events)

    captured_events = build_stream_span_events(
        content_event,
        settings=ProxySettings(
            observability_capture_content=True,
            observability_capture_responses=True,
        ),
        first_content_delta=True,
    )

    assert "secret answer" in captured_events[0]["attributes"]["output.value"]

    tool_event = NormalizedStreamEvent(
        type="tool_call_delta",
        model="GigaChat",
        tool_call=NormalizedToolCall(
            name="lookup",
            arguments={"api_key": "secret"},
        ),
    )
    tool_events = build_stream_span_events(
        tool_event,
        settings=ProxySettings(
            observability_capture_content=True,
            observability_capture_tool_args=True,
        ),
    )

    assert tool_events[0]["name"] == "stream.tool_call_delta"
    assert '"api_key": "***"' in tool_events[0]["attributes"]["llm.tool_calls"]
    assert "secret" not in tool_events[0]["attributes"]["llm.tool_calls"]


def test_openai_response_stream_observer_synthesizes_failed_response_after_error():
    observer = OpenAIResponseStreamObserver(settings=capture_off_settings())
    observer.observe_payload(
        "response.created",
        {
            "type": "response.created",
            "response": {
                "id": "resp_1",
                "object": "response",
                "status": "in_progress",
                "model": "GigaChat",
                "output": [],
            },
        },
    )
    observer.observe_payload(
        "error",
        {
            "type": "error",
            "code": "stream_error",
            "message": "boom",
            "sequence_number": 2,
        },
    )

    response = observer.to_response_payload({"model": "GigaChat"})
    event_names = [event["name"] for event in observer.events]

    assert response["id"] == "resp_1"
    assert response["status"] == "failed"
    assert response["error"]["message"] == "boom"
    assert "stream.start" in event_names
    assert "stream.error" in event_names


async def test_otel_sink_records_span_and_flushes_provider():
    class FakeSpan:
        def __init__(self, *, start_time=None):
            self.attributes = {}
            self.events = []
            self.start_time = start_time
            self.status = None

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def add_event(self, name, attributes=None):
            self.events.append((name, attributes or {}))

        def set_status(self, status):
            self.status = status

    class SpanContext:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTracer:
        def __init__(self):
            self.spans = []

        def start_as_current_span(self, name, start_time=None):
            span = FakeSpan(start_time=start_time)
            span.name = name
            self.spans.append(span)
            return SpanContext(span)

    class FakeProvider:
        def __init__(self):
            self.flushed = False

        def force_flush(self):
            self.flushed = True

    tracer = FakeTracer()
    provider = FakeProvider()
    sink = OpenTelemetryObservabilitySink(
        tracer=tracer,
        tracer_provider=provider,
        sample_rate=1.0,
    )
    started_at = datetime.now(timezone.utc) - timedelta(milliseconds=250)
    context = RequestContext(
        request_id="req-1",
        trace_id="trace-1",
        span_id="span-1",
        protocol="openai",
        route="/v1/responses",
        method="POST",
        started_at=started_at,
    )

    await sink.emit(
        "gpt2giga.request",
        {"status_code": 200},
        context=context,
        events=[
            {
                "name": "stream.first_token",
                "attributes": {"response_body": {"content": "raw"}},
            }
        ],
    )
    await sink.flush()

    assert len(tracer.spans) == 1
    assert tracer.spans[0].name == "gpt2giga.request"
    assert tracer.spans[0].start_time == int(started_at.timestamp() * 1_000_000_000)
    assert tracer.spans[0].attributes["request_id"] == "req-1"
    assert tracer.spans[0].attributes["status_code"] == 200
    assert tracer.spans[0].attributes["latency_ms"] >= 200
    assert tracer.spans[0].attributes["status"] == "ok"
    assert tracer.spans[0].attributes["otel.status_code"] == "OK"
    assert_span_status_code(tracer.spans[0].status, "OK")
    assert tracer.spans[0].events == [("stream.first_token", {})]
    assert provider.flushed is True


async def test_otel_sink_marks_failed_span_status():
    class FakeSpan:
        def __init__(self):
            self.attributes = {}
            self.status = None

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def set_status(self, status):
            self.status = status

    class SpanContext:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTracer:
        def __init__(self):
            self.spans = []

        def start_as_current_span(self, name):
            span = FakeSpan()
            self.spans.append(span)
            return SpanContext(span)

    tracer = FakeTracer()
    sink = OpenTelemetryObservabilitySink(tracer=tracer, sample_rate=1.0)

    await sink.emit(
        "gpt2giga.request",
        {"status_code": 500, "error_type": "RuntimeError"},
    )

    assert tracer.spans[0].attributes["status"] == "failed"
    assert tracer.spans[0].attributes["otel.status_code"] == "ERROR"
    assert_span_status_code(tracer.spans[0].status, "ERROR")


async def test_otel_sink_honors_zero_sample_rate():
    class FakeTracer:
        spans = []

        def start_as_current_span(self, name):  # pragma: no cover - must not be called
            raise AssertionError("unexpected span")

    sink = OpenTelemetryObservabilitySink(tracer=FakeTracer(), sample_rate=0.0)

    await sink.emit("gpt2giga.request", {"status_code": 200})


async def test_observability_safe_helpers_do_not_raise_on_sink_errors():
    class BrokenSink:
        async def emit(self, name, attributes=None, *, context=None):
            raise RuntimeError("emit failed")

        async def flush(self):
            raise RuntimeError("flush failed")

    sink = BrokenSink()

    await emit_observability_event(sink, "request.failed")
    await flush_observability_sink(sink)


async def test_observability_emit_timeout_returns_false(monkeypatch):
    class SlowSink:
        async def emit(self, name, attributes=None, *, context=None):
            await asyncio.sleep(1)

        async def flush(self):
            return None

    monkeypatch.setattr(
        "gpt2giga.sinks.observability.factory.DEFAULT_OBSERVABILITY_TIMEOUT_SECONDS",
        0.001,
    )

    emitted = await emit_observability_event(SlowSink(), "request.slow")

    assert emitted is False


async def test_otel_sink_runs_span_work_off_event_loop_thread():
    event_loop_thread_id = threading.get_ident()

    class FakeSpan:
        def __init__(self):
            self.thread_id = threading.get_ident()

        def set_attribute(self, key, value):
            return None

        def set_status(self, status):
            return None

    class SpanContext:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTracer:
        def __init__(self):
            self.spans = []

        def start_as_current_span(self, name, start_time=None):
            span = FakeSpan()
            self.spans.append(span)
            return SpanContext(span)

    tracer = FakeTracer()
    sink = OpenTelemetryObservabilitySink(tracer=tracer, sample_rate=1.0)

    await sink.emit("gpt2giga.request", {"status_code": 200})

    assert len(tracer.spans) == 1
    assert tracer.spans[0].thread_id != event_loop_thread_id


async def test_otel_sink_flush_runs_off_event_loop_thread():
    event_loop_thread_id = threading.get_ident()

    class FakeProvider:
        def __init__(self):
            self.thread_id = None

        def force_flush(self):
            self.thread_id = threading.get_ident()

    class FakeTracer:
        def start_as_current_span(self, name, start_time=None):
            raise AssertionError("unexpected span")

    provider = FakeProvider()
    sink = OpenTelemetryObservabilitySink(
        tracer=FakeTracer(),
        tracer_provider=provider,
        sample_rate=0.0,
    )

    await sink.flush()

    assert provider.thread_id != event_loop_thread_id


async def test_response_observability_uses_previous_response_id_as_session():
    class RecordingSink:
        def __init__(self):
            self.events = []

        async def emit(self, name, attributes=None, *, context=None, events=None):
            self.events.append((name, attributes or {}, context, list(events or [])))

        async def flush(self):
            return None

    sink = RecordingSink()
    state = SimpleNamespace(
        observability_sink=sink,
        config=SimpleNamespace(proxy_settings=capture_off_settings()),
        logger=None,
    )

    await emit_openai_response_observability(
        state,
        {
            "model": "gpt-x",
            "input": "hi",
            "previous_response_id": "resp_thread_1",
        },
        {
            "id": "resp_new",
            "model": "gpt-x",
            "status": "completed",
            "output": [],
            "usage": None,
        },
        context=None,
    )

    name, attributes, _context, events = sink.events[0]
    assert name == "Responses"
    assert attributes["gpt2giga.api_format"] == "responses"
    assert attributes["session.id"] == "thread_1"
    assert attributes["conversation.id"] == "thread_1"
    assert events == []
