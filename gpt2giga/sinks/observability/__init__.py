"""Observability sink namespace."""

from gpt2giga.sinks.observability.emission import (
    emit_request_observability_event,
    traffic_event_to_observability_attributes,
    wrap_observability_body_iterator,
)
from gpt2giga.sinks.observability.factory import (
    create_observability_sink,
    emit_observability_event,
    flush_observability_sink,
)
from gpt2giga.sinks.observability.llm import (
    CHAT_COMPLETION_SPAN_NAME,
    NORMALIZE_REQUEST_SPAN_NAME,
    NORMALIZE_RESPONSE_SPAN_NAME,
    STREAM_SPAN_NAME,
    build_llm_chat_completion_attributes,
    build_llm_request_attributes,
    build_llm_response_attributes,
    build_stream_event_attributes,
    build_stream_span_events,
)
from gpt2giga.sinks.observability.noop import NoopObservabilitySink
from gpt2giga.sinks.observability.otel import (
    OpenTelemetryObservabilitySink,
    build_otel_attributes,
)
from gpt2giga.sinks.observability.phoenix import create_phoenix_observability_sink

__all__ = [
    "NoopObservabilitySink",
    "OpenTelemetryObservabilitySink",
    "CHAT_COMPLETION_SPAN_NAME",
    "NORMALIZE_REQUEST_SPAN_NAME",
    "NORMALIZE_RESPONSE_SPAN_NAME",
    "STREAM_SPAN_NAME",
    "build_otel_attributes",
    "build_llm_chat_completion_attributes",
    "build_llm_request_attributes",
    "build_llm_response_attributes",
    "build_stream_event_attributes",
    "build_stream_span_events",
    "create_observability_sink",
    "create_phoenix_observability_sink",
    "emit_observability_event",
    "emit_request_observability_event",
    "flush_observability_sink",
    "traffic_event_to_observability_attributes",
    "wrap_observability_body_iterator",
]
