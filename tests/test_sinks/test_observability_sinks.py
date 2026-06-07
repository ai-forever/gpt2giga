import pytest
from datetime import datetime, timezone

from gpt2giga.core.context import RequestContext
from gpt2giga.core.interfaces import ObservabilitySink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.observability.factory import (
    create_observability_sink,
    emit_observability_event,
    flush_observability_sink,
)
from gpt2giga.sinks.observability.noop import NoopObservabilitySink
from gpt2giga.sinks.observability.otel import (
    OpenTelemetryObservabilitySink,
    build_otel_attributes,
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
    assert attributes["status_code"] == 200
    assert attributes["authorization"] == "***"
    assert "request_body" not in attributes
    assert attributes["metadata"] == '{"nested": true}'


@pytest.mark.asyncio
async def test_otel_sink_records_span_and_flushes_provider():
    class FakeSpan:
        def __init__(self):
            self.attributes = {}

        def set_attribute(self, key, value):
            self.attributes[key] = value

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

    await sink.emit("gpt2giga.request", {"status_code": 200})
    await sink.flush()

    assert len(tracer.spans) == 1
    assert tracer.spans[0].name == "gpt2giga.request"
    assert tracer.spans[0].attributes["status_code"] == 200
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
