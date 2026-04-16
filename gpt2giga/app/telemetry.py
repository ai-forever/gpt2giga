"""Pluggable telemetry sinks built on top of normalized request audit events."""

from __future__ import annotations

from gpt2giga.app._telemetry.builtin import register_builtin_sinks
from gpt2giga.app._telemetry.contracts import (
    ObservabilitySink,
    ObservabilitySinkDescriptor,
    ObservabilitySinkFactory,
)
from gpt2giga.app._telemetry.hub import ObservabilityHub
from gpt2giga.app._telemetry.langfuse import (
    LangfuseTraceSink,
    _build_langfuse_attributes,
    _build_langfuse_endpoint,
    _build_langfuse_headers,
)
from gpt2giga.app._telemetry.otlp import (
    OtlpHttpTraceSink,
    _OTLP_PROTOBUF_TRACES_CONTENT_TYPE,
    _OTLP_TRACES_CONTENT_TYPE,
    _build_default_resource_attributes,
    _build_otlp_headers,
    _build_otlp_span_attributes,
    _build_otlp_traces_payload,
    _build_otlp_traces_protobuf_payload,
    _resolve_otlp_endpoint,
)
from gpt2giga.app._telemetry.phoenix import (
    PhoenixTraceSink,
    _build_phoenix_attributes,
    _build_phoenix_endpoint,
    _build_phoenix_headers,
    _build_phoenix_resource_attributes,
)
from gpt2giga.app._telemetry.prometheus import (
    PrometheusMetricsSink,
    prometheus_content_type,
)
from gpt2giga.app._telemetry.registry import (
    create_observability_hub,
    register_observability_sink,
)

register_builtin_sinks()

__all__ = [
    "LangfuseTraceSink",
    "ObservabilityHub",
    "ObservabilitySink",
    "ObservabilitySinkDescriptor",
    "ObservabilitySinkFactory",
    "OtlpHttpTraceSink",
    "PhoenixTraceSink",
    "PrometheusMetricsSink",
    "_OTLP_PROTOBUF_TRACES_CONTENT_TYPE",
    "_OTLP_TRACES_CONTENT_TYPE",
    "_build_default_resource_attributes",
    "_build_langfuse_attributes",
    "_build_langfuse_endpoint",
    "_build_langfuse_headers",
    "_build_otlp_headers",
    "_build_otlp_span_attributes",
    "_build_otlp_traces_payload",
    "_build_otlp_traces_protobuf_payload",
    "_build_phoenix_attributes",
    "_build_phoenix_endpoint",
    "_build_phoenix_headers",
    "_build_phoenix_resource_attributes",
    "_resolve_otlp_endpoint",
    "create_observability_hub",
    "prometheus_content_type",
    "register_observability_sink",
]
