"""Phoenix/OpenTelemetry observability sink factory."""

from __future__ import annotations

from typing import Any

from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.observability.otel import OpenTelemetryObservabilitySink


def create_phoenix_observability_sink(
    settings: ProxySettings,
) -> OpenTelemetryObservabilitySink:
    """Create an OpenTelemetry sink configured for Phoenix OTLP export."""
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - exercised through factory fallback
        raise ImportError(
            "Install gpt2giga with the 'phoenix' extra to use Phoenix observability."
        ) from exc

    headers = _phoenix_headers(settings.phoenix_api_key)
    exporter = OTLPSpanExporter(
        endpoint=settings.phoenix_collector_endpoint,
        headers=headers,
    )
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "gpt2giga",
                "project.name": settings.phoenix_project_name,
                "openinference.project.name": settings.phoenix_project_name,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    tracer = provider.get_tracer("gpt2giga")
    return OpenTelemetryObservabilitySink(
        tracer=tracer,
        tracer_provider=provider,
        sample_rate=settings.observability_sample_rate,
        capture_content=settings.observability_capture_content,
        redaction_enabled=settings.observability_redaction_enabled,
    )


def _phoenix_headers(api_key: str | None) -> dict[str, Any] | None:
    if not api_key:
        return None
    return {"authorization": f"Bearer {api_key}"}
