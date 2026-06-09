"""Request lifecycle observability emission helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Mapping
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.sinks.logs.emission import build_request_traffic_event
from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.observability.factory import emit_observability_event

REQUEST_SPAN_NAME = "gpt2giga.request"


async def emit_request_observability_event(
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
    """Emit one request lifecycle observability span best effort."""
    if sink is None:
        return
    if _should_skip_request_lifecycle_span(context, lifecycle):
        return
    event = build_request_traffic_event(
        context,
        status_code=status_code,
        lifecycle=lifecycle,
        error_type=error_type,
        error_message=error_message,
        metadata=metadata,
    )
    attributes = traffic_event_to_observability_attributes(
        event, is_streaming=is_streaming
    )
    await emit_observability_event(
        sink,
        REQUEST_SPAN_NAME,
        attributes,
        context=context,
        events=_stream_lifecycle_events(lifecycle, attributes)
        if is_streaming
        else None,
        logger=logger,
    )


async def wrap_observability_body_iterator(
    body_iterator: AsyncIterator[Any],
    *,
    sink: Any,
    context: RequestContext,
    status_code: int,
    is_streaming: bool,
    logger: Any | None = None,
) -> AsyncIterator[Any]:
    """Emit request/stream observability spans after body consumption."""
    try:
        async for chunk in body_iterator:
            yield chunk
    except asyncio.CancelledError:
        await emit_request_observability_event(
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
        await emit_request_observability_event(
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
        await emit_request_observability_event(
            sink,
            context,
            status_code=status_code,
            lifecycle="streaming_completed" if is_streaming else "request_completed",
            logger=logger,
            is_streaming=is_streaming,
        )


def traffic_event_to_observability_attributes(
    event: TrafficLogEvent,
    *,
    is_streaming: bool = False,
) -> dict[str, Any]:
    """Map safe traffic event fields to span attributes."""
    attributes = {
        "request_id": event.request_id,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "protocol": event.protocol,
        "route": event.route,
        "method": event.method,
        "status_code": event.status_code,
        "model_requested": event.model_requested,
        "model_effective": event.model_effective,
        "provider": event.provider,
        "stream": is_streaming,
        "latency_ms": event.latency_ms,
        "upstream_latency_ms": event.upstream_latency_ms,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "total_tokens": event.total_tokens,
        "error_type": event.error_type,
        "metadata": event.metadata,
    }
    annotations = event.metadata.get("annotations")
    if isinstance(annotations, Mapping):
        attributes["annotations"] = annotations
        caller = annotations.get("caller")
        if isinstance(caller, Mapping):
            attributes.update(_caller_observability_attributes(caller))
    return attributes


def _stream_lifecycle_events(
    lifecycle: str,
    attributes: dict[str, Any],
) -> list[dict[str, Any]]:
    if lifecycle == "streaming_completed":
        name = "stream.completed"
    elif lifecycle == "streaming_aborted":
        name = "stream.aborted"
    elif lifecycle == "request_error":
        name = "stream.error"
    else:
        return []
    return [{"name": name, "attributes": attributes}]


def _should_skip_request_lifecycle_span(
    context: RequestContext,
    lifecycle: str,
) -> bool:
    if not context.llm_observability_emitted:
        return False
    return lifecycle in {"request_completed", "streaming_completed"}


def _caller_observability_attributes(caller: Mapping[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "name",
        "category",
        "client_family",
        "sdk",
        "agent",
        "ui",
        "user_agent",
        "agent_id",
    }
    return {
        f"caller.{key}": value
        for key, value in caller.items()
        if key in allowed_keys and value is not None
    }
