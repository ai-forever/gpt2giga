"""Request lifecycle metrics emission helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.sinks.logs.emission import build_request_traffic_event
from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.metrics.factory import (
    emit_metric_increment,
    emit_metric_observation,
)

REQUESTS_TOTAL = "gpt2giga_requests_total"
REQUEST_DURATION_SECONDS = "gpt2giga_request_duration_seconds"
UPSTREAM_DURATION_SECONDS = "gpt2giga_upstream_duration_seconds"
UPSTREAM_ERRORS_TOTAL = "gpt2giga_upstream_errors_total"
TOKENS_INPUT_TOTAL = "gpt2giga_tokens_input_total"
TOKENS_OUTPUT_TOTAL = "gpt2giga_tokens_output_total"
STREAM_DISCONNECTS_TOTAL = "gpt2giga_stream_disconnects_total"
TRAFFIC_LOG_DROPPED_TOTAL = "gpt2giga_traffic_log_dropped_total"


async def emit_request_metrics(
    sink: Any,
    context: RequestContext,
    *,
    status_code: int | None,
    lifecycle: str,
    logger: Any | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    is_streaming: bool = False,
) -> None:
    """Emit aggregate request metrics without propagating sink failures."""
    if sink is None:
        return
    event = build_request_traffic_event(
        context,
        status_code=status_code,
        lifecycle=lifecycle,
        error_type=error_type,
        error_message=error_message,
        metadata=metadata,
    )
    await emit_metrics_from_traffic_event(
        sink,
        event,
        is_streaming=is_streaming,
        logger=logger,
    )


async def emit_metrics_from_traffic_event(
    sink: Any,
    event: TrafficLogEvent,
    *,
    is_streaming: bool = False,
    logger: Any | None = None,
) -> None:
    """Map one request lifecycle event to baseline Prometheus metrics."""
    labels = _request_labels(event)
    await emit_metric_increment(sink, REQUESTS_TOTAL, 1, labels, logger=logger)
    if event.latency_ms is not None:
        await emit_metric_observation(
            sink,
            REQUEST_DURATION_SECONDS,
            event.latency_ms / 1000,
            labels,
            logger=logger,
        )
    if event.upstream_latency_ms is not None:
        await emit_metric_observation(
            sink,
            UPSTREAM_DURATION_SECONDS,
            event.upstream_latency_ms / 1000,
            _provider_labels(event),
            logger=logger,
        )
    if _is_upstream_error(event):
        await emit_metric_increment(
            sink,
            UPSTREAM_ERRORS_TOTAL,
            1,
            _provider_labels(event),
            logger=logger,
        )
    if event.input_tokens is not None:
        await emit_metric_increment(
            sink,
            TOKENS_INPUT_TOTAL,
            event.input_tokens,
            _token_labels(event),
            logger=logger,
        )
    if event.output_tokens is not None:
        await emit_metric_increment(
            sink,
            TOKENS_OUTPUT_TOTAL,
            event.output_tokens,
            _token_labels(event),
            logger=logger,
        )
    if is_streaming and _is_stream_disconnect(event):
        await emit_metric_increment(
            sink,
            STREAM_DISCONNECTS_TOTAL,
            1,
            _provider_labels(event),
            logger=logger,
        )


async def wrap_metrics_body_iterator(
    body_iterator: AsyncIterator[Any],
    *,
    sink: Any,
    context: RequestContext,
    status_code: int,
    is_streaming: bool,
    logger: Any | None = None,
) -> AsyncIterator[Any]:
    """Emit request/stream metrics after the response body is consumed."""
    try:
        async for chunk in body_iterator:
            yield chunk
    except asyncio.CancelledError:
        await emit_request_metrics(
            sink,
            context,
            status_code=499,
            lifecycle="streaming_aborted" if is_streaming else "request_aborted",
            logger=logger,
            error_type="stream_cancelled" if is_streaming else "request_cancelled",
            is_streaming=is_streaming,
        )
        raise
    except Exception as exc:
        await emit_request_metrics(
            sink,
            context,
            status_code=status_code if status_code >= 400 else 500,
            lifecycle="streaming_aborted" if is_streaming else "request_error",
            logger=logger,
            error_type=type(exc).__name__,
            error_message=str(exc),
            is_streaming=is_streaming,
        )
        raise
    else:
        await emit_request_metrics(
            sink,
            context,
            status_code=status_code,
            lifecycle="streaming_completed" if is_streaming else "request_completed",
            logger=logger,
            is_streaming=is_streaming,
        )


def refresh_traffic_log_drop_metric(metrics_sink: Any, traffic_log_sink: Any) -> None:
    """Refresh traffic log drop counter from queue-backed traffic log sinks."""
    set_counter = getattr(metrics_sink, "set_counter", None)
    if set_counter is None:
        return
    set_counter(
        TRAFFIC_LOG_DROPPED_TOTAL,
        _traffic_log_dropped_count(traffic_log_sink),
        {"sink": "all"},
    )


def _request_labels(event: TrafficLogEvent) -> dict[str, Any]:
    labels = {
        "protocol": event.protocol,
        "route": event.route,
        "method": event.method,
        "status_code": event.status_code,
        "lifecycle": event.metadata.get("lifecycle"),
    }
    if event.provider:
        labels["provider"] = event.provider
    return labels


def _provider_labels(event: TrafficLogEvent) -> dict[str, Any]:
    return {
        "protocol": event.protocol,
        "route": event.route,
        "provider": event.provider or "unknown",
        "error_type": event.error_type,
    }


def _token_labels(event: TrafficLogEvent) -> dict[str, Any]:
    return {
        "protocol": event.protocol,
        "route": event.route,
        "provider": event.provider or "unknown",
        "model": event.model_effective or event.model_requested,
    }


def _is_upstream_error(event: TrafficLogEvent) -> bool:
    lifecycle = event.metadata.get("lifecycle")
    return bool(event.error_type and lifecycle == "upstream_error")


def _is_stream_disconnect(event: TrafficLogEvent) -> bool:
    lifecycle = event.metadata.get("lifecycle")
    return lifecycle == "streaming_aborted" and event.error_type == "stream_cancelled"


def _traffic_log_dropped_count(sink: Any) -> int:
    if sink is None:
        return 0
    count = getattr(sink, "dropped_events", None)
    if isinstance(count, int):
        return max(count, 0)
    child_sinks = getattr(sink, "sinks", None)
    if isinstance(child_sinks, list):
        return sum(_traffic_log_dropped_count(child) for child in child_sinks)
    wrapped = getattr(sink, "sink", None)
    if wrapped is not None and wrapped is not sink:
        return _traffic_log_dropped_count(wrapped)
    return 0
