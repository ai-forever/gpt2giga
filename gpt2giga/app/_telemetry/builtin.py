"""Built-in sink registrations."""

from __future__ import annotations

from typing import Any

from .contracts import ObservabilitySinkDescriptor
from .langfuse import (
    LangfuseTraceSink,
    _build_langfuse_attributes,
    _build_langfuse_endpoint,
    _build_langfuse_headers,
)
from .otlp import (
    OtlpHttpTraceSink,
    _OTLP_PROTOBUF_TRACES_CONTENT_TYPE,
    _build_default_resource_attributes,
    _build_otlp_headers,
    _build_otlp_traces_protobuf_payload,
    _resolve_otlp_endpoint,
)
from .phoenix import (
    PhoenixTraceSink,
    _build_phoenix_attributes,
    _build_phoenix_endpoint,
    _build_phoenix_headers,
    _build_phoenix_resource_attributes,
)
from .prometheus import PrometheusMetricsSink
from .registry import register_observability_sink

_BUILTINS_REGISTERED = False


def register_builtin_sinks() -> None:
    """Register the built-in telemetry sinks once."""
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return

    register_observability_sink(
        ObservabilitySinkDescriptor(
            name="prometheus",
            description="Built-in Prometheus counters and latency histograms.",
            factory=lambda **_: PrometheusMetricsSink(),
        )
    )
    register_observability_sink(
        ObservabilitySinkDescriptor(
            name="otlp",
            description="Built-in OTLP/HTTP trace exporter for normalized request events.",
            factory=lambda **kwargs: OtlpHttpTraceSink(
                endpoint=_resolve_otlp_endpoint(kwargs.get("config")),
                headers=_build_otlp_headers(kwargs.get("config")),
                resource_attributes=_build_default_resource_attributes(
                    kwargs.get("config")
                ),
                logger=kwargs.get("logger"),
                max_pending_requests=_otlp_runtime_setting(
                    kwargs.get("config"),
                    "max_pending_requests",
                    256,
                ),
                timeout_seconds=_otlp_runtime_setting(
                    kwargs.get("config"),
                    "timeout_seconds",
                    5.0,
                ),
            ),
        )
    )
    register_observability_sink(
        ObservabilitySinkDescriptor(
            name="langfuse",
            description="Built-in Langfuse OTLP/HTTP trace exporter.",
            factory=lambda **kwargs: LangfuseTraceSink(
                endpoint=_build_langfuse_endpoint(kwargs.get("config")),
                headers=_build_langfuse_headers(kwargs.get("config")),
                resource_attributes=_build_default_resource_attributes(
                    kwargs.get("config")
                ),
                logger=kwargs.get("logger"),
                max_pending_requests=_otlp_runtime_setting(
                    kwargs.get("config"),
                    "max_pending_requests",
                    256,
                ),
                timeout_seconds=_otlp_runtime_setting(
                    kwargs.get("config"),
                    "timeout_seconds",
                    5.0,
                ),
                attribute_enricher=_build_langfuse_attributes,
            ),
        )
    )
    register_observability_sink(
        ObservabilitySinkDescriptor(
            name="phoenix",
            description="Built-in Phoenix OTLP/HTTP trace exporter.",
            factory=lambda **kwargs: PhoenixTraceSink(
                endpoint=_build_phoenix_endpoint(kwargs.get("config")),
                headers=_build_phoenix_headers(kwargs.get("config")),
                resource_attributes=_build_phoenix_resource_attributes(
                    kwargs.get("config")
                ),
                logger=kwargs.get("logger"),
                max_pending_requests=_otlp_runtime_setting(
                    kwargs.get("config"),
                    "max_pending_requests",
                    256,
                ),
                timeout_seconds=_otlp_runtime_setting(
                    kwargs.get("config"),
                    "timeout_seconds",
                    5.0,
                ),
                attribute_enricher=_build_phoenix_attributes,
                content_type=_OTLP_PROTOBUF_TRACES_CONTENT_TYPE,
                payload_builder=_build_otlp_traces_protobuf_payload,
            ),
        )
    )
    _BUILTINS_REGISTERED = True


def _otlp_runtime_setting(config: Any | None, name: str, default: Any) -> Any:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    otlp = getattr(observability, "otlp", None)
    return getattr(
        otlp,
        name,
        getattr(proxy_settings, f"otlp_{name}", default),
    )
