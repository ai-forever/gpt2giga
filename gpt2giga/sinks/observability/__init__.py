"""Observability sink namespace."""

from gpt2giga.sinks.observability.factory import (
    create_observability_sink,
    emit_observability_event,
    flush_observability_sink,
)
from gpt2giga.sinks.observability.noop import NoopObservabilitySink

__all__ = [
    "NoopObservabilitySink",
    "create_observability_sink",
    "emit_observability_event",
    "flush_observability_sink",
]
