"""Traffic log event emission helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.sinks.logs.factory import emit_traffic_log
from gpt2giga.sinks.logs.models import TrafficLogEvent

STREAMING_CONTENT_TYPES = ("text/event-stream",)


def build_request_traffic_event(
    context: RequestContext,
    *,
    status_code: int | None,
    lifecycle: str,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TrafficLogEvent:
    """Build one safe traffic log event from request context."""
    merged_metadata = dict(context.metadata)
    merged_metadata["lifecycle"] = lifecycle
    if metadata:
        merged_metadata.update(metadata)
    if error_type is None and status_code is not None and status_code >= 400:
        error_type = f"http_{status_code}"
    return TrafficLogEvent(
        created_at=context.started_at,
        request_id=context.request_id,
        trace_id=context.trace_id,
        span_id=context.span_id,
        protocol=context.protocol,
        route=context.route,
        method=context.method,
        status_code=status_code,
        model_requested=context.model_requested,
        model_effective=context.model_effective,
        provider=_provider_for_protocol(context.protocol),
        latency_ms=_latency_ms(context.started_at),
        error_type=error_type,
        error_message=error_message,
        api_key_hash=context.api_key_hash,
        client_ip_hash=context.client_ip_hash,
        metadata=merged_metadata,
    )


async def emit_request_traffic_event(
    sink: Any,
    context: RequestContext,
    *,
    status_code: int | None,
    lifecycle: str,
    logger: Any | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit one request traffic event without propagating sink failures."""
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
    await emit_traffic_log(sink, event, logger=logger)


async def wrap_traffic_log_body_iterator(
    body_iterator: AsyncIterator[Any],
    *,
    sink: Any,
    context: RequestContext,
    status_code: int,
    is_streaming: bool,
    logger: Any | None = None,
) -> AsyncIterator[Any]:
    """Emit request/stream traffic events after the response body is consumed."""
    try:
        async for chunk in body_iterator:
            yield chunk
    except asyncio.CancelledError:
        await emit_request_traffic_event(
            sink,
            context,
            status_code=499,
            lifecycle="streaming_aborted" if is_streaming else "request_aborted",
            logger=logger,
            error_type="stream_cancelled" if is_streaming else "request_cancelled",
        )
        raise
    except Exception as exc:
        await emit_request_traffic_event(
            sink,
            context,
            status_code=status_code if status_code >= 400 else 500,
            lifecycle="streaming_aborted" if is_streaming else "request_error",
            logger=logger,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise
    else:
        await emit_request_traffic_event(
            sink,
            context,
            status_code=status_code,
            lifecycle="streaming_completed" if is_streaming else "request_completed",
            logger=logger,
        )


def is_streaming_content_type(content_type: str | None) -> bool:
    """Return whether a response content type represents an event stream."""
    if not content_type:
        return False
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized in STREAMING_CONTENT_TYPES


def _latency_ms(started_at: datetime) -> float:
    return (datetime.now(timezone.utc) - started_at).total_seconds() * 1000


def _provider_for_protocol(protocol: str) -> str | None:
    if protocol in {"openai", "anthropic"}:
        return "gigachat"
    return None
