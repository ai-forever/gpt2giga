"""OpenTelemetry-backed observability sink helpers."""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
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

        span_attributes = build_otel_attributes(
            attributes,
            context=context,
            capture_content=self.capture_content,
            redaction_enabled=self.redaction_enabled,
        )
        with self.tracer.start_as_current_span(name) as span:
            for key, value in span_attributes.items():
                span.set_attribute(key, value)
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
