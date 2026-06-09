import pytest
from datetime import datetime, timezone

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
)
from gpt2giga.sinks.observability.noop import NoopObservabilitySink
from gpt2giga.sinks.observability.otel import (
    OpenTelemetryObservabilitySink,
    build_otel_attributes,
)


def capture_off_settings() -> ProxySettings:
    return ProxySettings(
        observability_capture_content=False,
        observability_capture_messages=False,
        observability_capture_tool_args=False,
        observability_capture_responses=False,
    )


@pytest.mark.asyncio
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
    assert default_attributes["llm.response.metadata"] == (
        '{"gigachat_x_request_id": "rq-1"}'
    )
    assert default_attributes["llm.token_count.prompt"] == 3
    assert default_attributes["llm.token_count.completion"] == 5
    assert default_attributes["llm.token_count.total"] == 8
    assert "private answer" not in str(default_attributes)
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
    assert '"password": "***"' in captured_attributes["llm.tool_calls"]
    assert "secret" not in captured_attributes["llm.tool_calls"]


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


@pytest.mark.asyncio
async def test_otel_sink_records_span_and_flushes_provider():
    class FakeSpan:
        def __init__(self):
            self.attributes = {}
            self.events = []

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def add_event(self, name, attributes=None):
            self.events.append((name, attributes or {}))

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

    await sink.emit(
        "gpt2giga.request",
        {"status_code": 200},
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
    assert tracer.spans[0].attributes["status_code"] == 200
    assert tracer.spans[0].events == [("stream.first_token", {})]
    assert provider.flushed is True


@pytest.mark.asyncio
async def test_otel_sink_honors_zero_sample_rate():
    class FakeTracer:
        spans = []

        def start_as_current_span(self, name):  # pragma: no cover - must not be called
            raise AssertionError("unexpected span")

    sink = OpenTelemetryObservabilitySink(tracer=FakeTracer(), sample_rate=0.0)

    await sink.emit("gpt2giga.request", {"status_code": 200})


@pytest.mark.asyncio
async def test_observability_safe_helpers_do_not_raise_on_sink_errors():
    class BrokenSink:
        async def emit(self, name, attributes=None, *, context=None):
            raise RuntimeError("emit failed")

        async def flush(self):
            raise RuntimeError("flush failed")

    sink = BrokenSink()

    await emit_observability_event(sink, "request.failed")
    await flush_observability_sink(sink)
