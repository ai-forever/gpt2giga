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
from gpt2giga.sinks.observability.noop import NoopObservabilitySink
from gpt2giga.sinks.observability.otel import (
    OpenTelemetryObservabilitySink,
    build_otel_attributes,
)
from gpt2giga.sinks.observability.phoenix import create_phoenix_observability_sink

__all__ = [
    "NoopObservabilitySink",
    "OpenTelemetryObservabilitySink",
    "build_otel_attributes",
    "create_observability_sink",
    "create_phoenix_observability_sink",
    "emit_observability_event",
    "emit_request_observability_event",
    "flush_observability_sink",
    "traffic_event_to_observability_attributes",
    "wrap_observability_body_iterator",
]
