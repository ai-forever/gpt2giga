"""OpenTelemetry-backed observability sink helpers."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.core.redaction import redact_traffic_payload

CONTENT_ATTRIBUTE_KEYS = frozenset(
    {
        "content",
        "input",
        "input.value",
        "input.messages",
        "llm.input_messages",
        "llm.output_messages",
        "llm.tool_calls",
        "llm.tools",
        "messages",
        "output",
        "output.value",
        "output.messages",
        "prompt",
        "request.body",
        "request_body",
        "response.body",
        "response_body",
    }
)


class OpenTelemetryObservabilitySink:
    """Record observability events as short-lived OpenTelemetry spans."""

    def __init__(
        self,
        *,
        tracer: Any,
        tracer_provider: Any | None = None,
        sample_rate: float = 1.0,
        capture_content: bool = False,
        redaction_enabled: bool = True,
        random_fn: Any = random.random,
    ) -> None:
        self.tracer = tracer
        self.tracer_provider = tracer_provider
        self.sample_rate = sample_rate
        self.capture_content = capture_content
        self.redaction_enabled = redaction_enabled
        self._random_fn = random_fn

    async def emit(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        *,
        context: RequestContext | None = None,
        events: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Record one observability event as an OTel span."""
        if not self._should_sample():
            return

        ended_at = datetime.now(timezone.utc)
        span_attributes = build_otel_attributes(
            attributes,
            context=context,
            capture_content=self.capture_content,
            redaction_enabled=self.redaction_enabled,
        )
        if context is not None:
            latency_ms = _elapsed_ms(context.started_at, ended_at)
            if latency_ms is not None:
                span_attributes.setdefault("latency_ms", latency_ms)
        failed, description = _infer_span_status(span_attributes)
        span_attributes.setdefault("status", "failed" if failed else "ok")
        span_attributes.setdefault("otel.status_code", "ERROR" if failed else "OK")
        start_time = _datetime_to_unix_nano(context.started_at if context else None)
        with _start_span(self.tracer, name, start_time=start_time) as span:
            for key, value in span_attributes.items():
                span.set_attribute(key, value)
            _set_span_status(span, failed=failed, description=description)
            for event in events or ():
                event_name = str(event.get("name", "event"))
                event_attributes = build_otel_attributes(
                    _event_attributes(event),
                    capture_content=self.capture_content,
                    redaction_enabled=self.redaction_enabled,
                )
                add_event = getattr(span, "add_event", None)
                if add_event is not None:
                    add_event(event_name, event_attributes)

    async def flush(self) -> None:
        """Flush pending spans best effort."""
        force_flush = getattr(self.tracer_provider, "force_flush", None)
        if force_flush is not None:
            force_flush()

    def _should_sample(self) -> bool:
        if self.sample_rate <= 0:
            return False
        if self.sample_rate >= 1:
            return True
        return float(self._random_fn()) < self.sample_rate


def build_otel_attributes(
    attributes: Mapping[str, Any] | None = None,
    *,
    context: RequestContext | None = None,
    capture_content: bool = False,
    redaction_enabled: bool = True,
) -> dict[str, Any]:
    """Return OpenTelemetry-compatible scalar attributes."""
    payload: dict[str, Any] = {}
    if context is not None:
        payload.update(
            {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "span_id": context.span_id,
                "protocol": context.protocol,
                "route": context.route,
                "method": context.method,
                "model_requested": context.model_requested,
                "model_effective": context.model_effective,
                "caller.name": context.caller_name,
                "caller.category": context.caller_category,
                "caller.client_family": context.caller_client_family,
                "caller.sdk": context.caller_sdk,
                "caller.agent": context.caller_agent,
                "caller.ui": context.caller_ui,
                "caller.user_agent": context.caller_user_agent,
                "caller.agent_id": context.caller_agent_id,
            }
        )
        if context.annotations:
            payload["annotations"] = context.annotations
        if context.metadata:
            payload["metadata"] = context.metadata
            _apply_context_metadata_attributes(payload, context.metadata)
    payload.update(dict(attributes or {}))

    if redaction_enabled:
        payload = redact_traffic_payload(payload)

    return {
        key: _coerce_otel_attribute_value(value)
        for key, value in payload.items()
        if _should_keep_attribute(key, value, capture_content=capture_content)
    }


def _should_keep_attribute(
    key: str,
    value: Any,
    *,
    capture_content: bool,
) -> bool:
    if value is None:
        return False
    if capture_content:
        return True
    return key.lower() not in CONTENT_ATTRIBUTE_KEYS


def _coerce_otel_attribute_value(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        if all(isinstance(item, (str, bool, int, float)) for item in value):
            return list(value)
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _event_attributes(event: Mapping[str, Any]) -> Mapping[str, Any]:
    attributes = event.get("attributes")
    return attributes if isinstance(attributes, Mapping) else {}


def _apply_context_metadata_attributes(
    payload: dict[str, Any],
    metadata: Mapping[str, Any],
) -> None:
    conversation_id = metadata.get("conversation_id")
    if isinstance(conversation_id, str) and conversation_id:
        payload.setdefault("session.id", conversation_id)
        payload.setdefault("conversation.id", conversation_id)

    field_map = {
        "conversation_save_id": "conversation.save_id",
        "conversation_stitched": "conversation.stitched",
        "conversation_divergent": "conversation.divergent",
        "conversation_forked": "conversation.forked",
        "conversation_history_messages": "conversation.history_messages",
        "conversation_revision": "conversation.revision",
        "conversation_saved_messages": "conversation.saved_messages",
        "conversation_saved_revision": "conversation.saved_revision",
    }
    for source, target in field_map.items():
        value = metadata.get(source)
        if value is not None:
            payload.setdefault(target, value)


def _start_span(tracer: Any, name: str, *, start_time: int | None) -> Any:
    if start_time is None:
        return tracer.start_as_current_span(name)
    try:
        return tracer.start_as_current_span(name, start_time=start_time)
    except TypeError:
        return tracer.start_as_current_span(name)


def _datetime_to_unix_nano(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)


def _elapsed_ms(started_at: datetime, ended_at: datetime) -> float | None:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    value = (ended_at - started_at).total_seconds() * 1000
    if value < 0:
        return None
    return value


def _infer_span_status(attributes: Mapping[str, Any]) -> tuple[bool, str | None]:
    status = attributes.get("status")
    if isinstance(status, str):
        normalized = status.lower()
        if normalized in {"failed", "failure", "error", "errored"}:
            return True, _status_description(attributes)
        if normalized in {"ok", "success", "succeeded"}:
            return False, None

    status_code = attributes.get("status_code")
    if isinstance(status_code, str):
        try:
            status_code = int(status_code)
        except ValueError:
            status_code = None
    if isinstance(status_code, int) and status_code >= 400:
        return True, _status_description(attributes) or f"HTTP {status_code}"

    if attributes.get("error_type") or attributes.get("error.type"):
        return True, _status_description(attributes)
    if attributes.get("error_message") or attributes.get("error.message"):
        return True, _status_description(attributes)

    return False, None


def _status_description(attributes: Mapping[str, Any]) -> str | None:
    for key in ("error_message", "error.message", "error_type", "error.type"):
        value = attributes.get(key)
        if value is not None:
            return str(value)
    return None


def _set_span_status(
    span: Any,
    *,
    failed: bool,
    description: str | None,
) -> None:
    set_status = getattr(span, "set_status", None)
    if set_status is None:
        return

    try:
        from opentelemetry.trace import Status, StatusCode

        status_code = StatusCode.ERROR if failed else StatusCode.OK
        set_status(Status(status_code, description if failed else None))
    except Exception:
        try:
            set_status("ERROR" if failed else "OK")
        except Exception:
            return
