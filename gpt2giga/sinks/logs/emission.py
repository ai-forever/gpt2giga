"""Traffic log event emission helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
import json

from gpt2giga.core.context import RequestContext
from gpt2giga.core.context import get_request_context
from gpt2giga.core.redaction import redact_traffic_payload
from gpt2giga.sinks.logs.factory import emit_traffic_log
from gpt2giga.sinks.logs.models import TrafficLogEvent

STREAMING_CONTENT_TYPES = ("text/event-stream",)
MAX_CAPTURED_RESPONSE_BODY_BYTES = 1_000_000


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
    if context.annotations:
        existing_annotations = merged_metadata.get("annotations")
        annotations = (
            dict(existing_annotations)
            if isinstance(existing_annotations, Mapping)
            else {}
        )
        annotations.update(context.annotations)
        merged_metadata["annotations"] = annotations
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
        request_headers_redacted=context.request_headers_redacted,
        request_body_redacted=context.request_body_redacted,
        response_body_redacted=context.response_body_redacted,
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
    capture_content: bool = False,
    redact_sensitive: bool = True,
    redact_extra_keys: list[str] | None = None,
    logger: Any | None = None,
) -> AsyncIterator[Any]:
    """Emit request/stream traffic events after the response body is consumed."""
    captured_chunks: list[bytes] = []
    captured_size = 0
    truncated = False
    try:
        async for chunk in body_iterator:
            if capture_content and not is_streaming and not truncated:
                chunk_bytes = _chunk_to_bytes(chunk)
                if chunk_bytes is not None:
                    remaining = MAX_CAPTURED_RESPONSE_BODY_BYTES - captured_size
                    if remaining > 0:
                        captured_chunks.append(chunk_bytes[:remaining])
                        captured_size += min(len(chunk_bytes), remaining)
                    if len(chunk_bytes) > remaining:
                        truncated = True
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
        if capture_content and not is_streaming:
            context.response_body_redacted = _decode_captured_body(
                b"".join(captured_chunks),
                truncated=truncated,
                redact_sensitive=redact_sensitive,
                redact_extra_keys=redact_extra_keys,
            )
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


def capture_traffic_request_headers(request: Any, context: RequestContext) -> None:
    """Capture redacted request headers when traffic-log content capture is enabled."""
    settings = _proxy_settings(request)
    if not getattr(settings, "traffic_log_capture_content", False):
        return
    context.request_headers_redacted = redact_traffic_payload(
        dict(request.headers),
        enabled=getattr(settings, "traffic_log_redact_sensitive", True),
        extra_keys=getattr(settings, "traffic_log_redact_extra_keys", None),
    )


def capture_traffic_request_body(request: Any, payload: Mapping[str, Any]) -> None:
    """Capture a redacted parsed JSON request body for traffic logs."""
    settings = _proxy_settings(request)
    if not getattr(settings, "traffic_log_capture_content", False):
        return
    context = get_request_context()
    if context is None:
        return
    context.request_body_redacted = redact_traffic_payload(
        dict(payload),
        enabled=getattr(settings, "traffic_log_redact_sensitive", True),
        extra_keys=getattr(settings, "traffic_log_redact_extra_keys", None),
    )


def _decode_captured_body(
    body: bytes,
    *,
    truncated: bool,
    redact_sensitive: bool,
    redact_extra_keys: list[str] | None,
) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        payload = text
    payload = redact_traffic_payload(
        payload,
        enabled=redact_sensitive,
        extra_keys=redact_extra_keys,
    )
    if not truncated:
        return payload
    return {
        "truncated": True,
        "max_bytes": MAX_CAPTURED_RESPONSE_BODY_BYTES,
        "body": payload,
    }


def _chunk_to_bytes(chunk: Any) -> bytes | None:
    if isinstance(chunk, bytes):
        return chunk
    if isinstance(chunk, str):
        return chunk.encode("utf-8")
    return None


def _proxy_settings(request: Any) -> Any:
    return getattr(getattr(request.app.state, "config", None), "proxy_settings", None)


def _latency_ms(started_at: datetime) -> float:
    return (datetime.now(timezone.utc) - started_at).total_seconds() * 1000


def _provider_for_protocol(protocol: str) -> str | None:
    if protocol in {"openai", "anthropic", "gemini"}:
        return "gigachat"
    return None
