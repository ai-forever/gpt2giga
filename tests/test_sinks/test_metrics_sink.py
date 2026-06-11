from datetime import datetime, timezone

import pytest

from gpt2giga.core.interfaces import MetricsSink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.metrics import (
    REQUESTS_TOTAL,
    REQUEST_DURATION_SECONDS,
    create_metrics_sink,
    emit_metrics_from_traffic_event,
    refresh_traffic_log_drop_metric,
)
from gpt2giga.sinks.metrics.noop import NoopMetricsSink
from gpt2giga.sinks.metrics.prometheus import PrometheusMetricsSink


@pytest.mark.asyncio
async def test_noop_metrics_sink_implements_contract():
    sink = NoopMetricsSink()

    assert isinstance(sink, MetricsSink)
    await sink.increment(REQUESTS_TOTAL, attributes={"route": "/v1/models"})
    await sink.observe(REQUEST_DURATION_SECONDS, 0.1)
    await sink.flush()


def test_metrics_factory_returns_noop_by_default():
    sink = create_metrics_sink(ProxySettings())

    assert isinstance(sink, NoopMetricsSink)


def test_metrics_factory_returns_prometheus_when_enabled():
    sink = create_metrics_sink(ProxySettings(metrics_enabled=True))

    assert isinstance(sink, PrometheusMetricsSink)


@pytest.mark.asyncio
async def test_prometheus_sink_renders_counters_histograms_and_safe_labels():
    sink = PrometheusMetricsSink()

    await sink.increment(
        REQUESTS_TOTAL,
        attributes={
            "route": "/v1/models",
            "method": "GET",
            "authorization": "Bearer secret",
            "request_id": "req-1",
            "prompt": "raw prompt",
        },
    )
    await sink.observe(
        REQUEST_DURATION_SECONDS,
        0.2,
        attributes={"route": "/v1/models", "method": "GET"},
    )

    text = sink.render()

    assert "# TYPE gpt2giga_requests_total counter" in text
    assert 'gpt2giga_requests_total{method="GET",route="/v1/models"} 1' in text
    assert (
        'gpt2giga_request_duration_seconds_bucket{method="GET",route="/v1/models",le="0.25"} 1'
        in text
    )
    assert "secret" not in text
    assert "request_id" not in text
    assert "raw prompt" not in text


@pytest.mark.asyncio
async def test_metrics_emission_maps_request_tokens_and_stream_disconnect():
    sink = PrometheusMetricsSink()
    event = TrafficLogEvent(
        created_at=datetime.now(timezone.utc),
        request_id="req-1",
        trace_id="trace-1",
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        status_code=499,
        model_requested="GigaChat",
        model_effective="GigaChat-2-Max",
        provider="gigachat",
        latency_ms=250,
        input_tokens=3,
        output_tokens=5,
        error_type="stream_cancelled",
        metadata={"lifecycle": "streaming_aborted"},
    )

    await emit_metrics_from_traffic_event(sink, event, is_streaming=True)

    text = sink.render()

    assert (
        'gpt2giga_requests_total{lifecycle="streaming_aborted",method="POST",protocol="openai",provider="gigachat",route="/v1/chat/completions",status_code="499"} 1'
        in text
    )
    assert (
        'gpt2giga_tokens_input_total{model="GigaChat-2-Max",protocol="openai",provider="gigachat",route="/v1/chat/completions"} 3'
        in text
    )
    assert (
        'gpt2giga_tokens_output_total{model="GigaChat-2-Max",protocol="openai",provider="gigachat",route="/v1/chat/completions"} 5'
        in text
    )
    assert (
        'gpt2giga_stream_disconnects_total{error_type="stream_cancelled",protocol="openai",provider="gigachat",route="/v1/chat/completions"} 1'
        in text
    )


def test_refresh_traffic_log_drop_metric_reads_queue_sinks():
    class QueueSink:
        dropped_events = 7

    sink = PrometheusMetricsSink()

    refresh_traffic_log_drop_metric(sink, QueueSink())

    assert 'gpt2giga_traffic_log_dropped_total{sink="all"} 7' in sink.render()
