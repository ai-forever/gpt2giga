"""Pluggable telemetry sinks built on top of normalized request audit events."""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from math import inf
from typing import Any

import aiohttp
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import (
    AnyValue,
    ArrayValue,
    InstrumentationScope,
    KeyValue,
)
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans,
    ScopeSpans,
    Span,
    Status,
)

from collections import defaultdict

_PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_OTLP_TRACES_CONTENT_TYPE = "application/json"
_OTLP_PROTOBUF_TRACES_CONTENT_TYPE = "application/x-protobuf"
_OTLP_HTTP_OK_STATUSES = {200, 202}
_OTLP_SCOPE_NAME = "gpt2giga.observability"
_OTLP_SCOPE_VERSION = "1.0.0"
_DEFAULT_REQUEST_BUCKETS_SECONDS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)
_DEFAULT_STREAM_BUCKETS_SECONDS: tuple[float, ...] = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)


class ObservabilitySink:
    """Base telemetry sink for normalized request audit events."""

    name = "base"

    async def open(self) -> None:
        """Initialize sink resources when needed."""

    async def close(self) -> None:
        """Tear down sink resources when needed."""

    def record_request_event(self, event: Mapping[str, Any]) -> None:
        """Consume a normalized request event."""

    def render_prometheus_text(self) -> str | None:
        """Return Prometheus exposition text when the sink supports it."""
        return None


class OtlpHttpTraceSink(ObservabilitySink):
    """Export normalized request events as OTLP/HTTP trace spans."""

    name = "otlp"

    def __init__(
        self,
        *,
        endpoint: str,
        headers: Mapping[str, str] | None = None,
        resource_attributes: Mapping[str, Any] | None = None,
        logger: Any | None = None,
        max_pending_requests: int = 256,
        timeout_seconds: float = 5.0,
        attribute_enricher: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
        content_type: str = _OTLP_TRACES_CONTENT_TYPE,
        payload_builder: (
            Callable[
                [
                    Mapping[str, Any],
                    Mapping[str, Any],
                    str,
                    str,
                    Callable[[Mapping[str, Any]], dict[str, Any]] | None,
                ],
                Mapping[str, Any] | bytes,
            ]
            | None
        ) = None,
    ) -> None:
        normalized_endpoint = str(endpoint).strip().rstrip("/")
        if not normalized_endpoint:
            raise RuntimeError(
                "OTLP endpoint must not be empty when the sink is enabled."
            )
        self._endpoint = normalized_endpoint
        self._headers = {
            key: str(value)
            for key, value in (headers or {}).items()
            if str(key).strip() and value is not None
        }
        self._resource_attributes = dict(resource_attributes or {})
        self._logger = logger
        self._max_pending_requests = max(1, int(max_pending_requests))
        self._timeout_seconds = max(0.1, float(timeout_seconds))
        self._attribute_enricher = attribute_enricher
        self._content_type = str(content_type).strip() or _OTLP_TRACES_CONTENT_TYPE
        self._payload_builder = payload_builder or _build_otlp_traces_payload
        self._session: aiohttp.ClientSession | None = None
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._drop_warning_emitted = False

    async def open(self) -> None:
        """Create the HTTP client session used for exports."""
        if self._session is not None and not self._session.closed:
            return
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        """Flush in-flight exports and close the HTTP client session."""
        pending = tuple(self._pending_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._pending_tasks.clear()
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        self._drop_warning_emitted = False

    def record_request_event(self, event: Mapping[str, Any]) -> None:
        """Schedule a non-blocking OTLP export for the normalized event."""
        if len(self._pending_tasks) >= self._max_pending_requests:
            if not self._drop_warning_emitted:
                self._drop_warning_emitted = True
                _log_warning(
                    self._logger,
                    "Observability sink `%s` dropped request events because the "
                    "pending OTLP queue reached %s items.",
                    self.name,
                    self._max_pending_requests,
                )
            return

        session = self._session
        if session is None or session.closed:
            _log_warning(
                self._logger,
                "Observability sink `%s` is not open; dropping OTLP export.",
                self.name,
            )
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _log_warning(
                self._logger,
                "Observability sink `%s` requires an active event loop; dropping OTLP export.",
                self.name,
            )
            return

        payload = self._payload_builder(
            event,
            resource_attributes=self._resource_attributes,
            scope_name=_OTLP_SCOPE_NAME,
            scope_version=_OTLP_SCOPE_VERSION,
            attribute_enricher=self._attribute_enricher,
        )
        task = loop.create_task(self._post_payload(payload))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _post_payload(self, payload: Mapping[str, Any] | bytes) -> None:
        headers = {"content-type": self._content_type, **self._headers}
        session = self._session
        if session is None or session.closed:
            return
        request_kwargs = (
            {"data": payload}
            if isinstance(payload, (bytes, bytearray))
            else {"json": payload}
        )
        try:
            async with session.post(
                self._endpoint, headers=headers, **request_kwargs
            ) as response:
                if response.status in _OTLP_HTTP_OK_STATUSES:
                    self._drop_warning_emitted = False
                    return
                body = (await response.text())[:500]
                _log_warning(
                    self._logger,
                    "Observability sink `%s` OTLP export failed with HTTP %s: %s",
                    self.name,
                    response.status,
                    body,
                )
        except Exception as exc:
            _log_warning(
                self._logger,
                "Observability sink `%s` OTLP export raised %s: %s",
                self.name,
                type(exc).__name__,
                exc,
            )


class LangfuseTraceSink(OtlpHttpTraceSink):
    """Export normalized request events to Langfuse via its OTLP/HTTP endpoint."""

    name = "langfuse"


class PhoenixTraceSink(OtlpHttpTraceSink):
    """Export normalized request events to Phoenix via its OTLP/HTTP endpoint."""

    name = "phoenix"


class _CounterMetric:
    """Simple Prometheus counter implementation with labels."""

    def __init__(
        self,
        name: str,
        help_text: str,
        *,
        label_names: tuple[str, ...],
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._samples: dict[tuple[str, ...], float] = defaultdict(float)

    def inc(self, *, labels: Mapping[str, str], amount: float = 1.0) -> None:
        """Increment a counter sample."""
        self._samples[_labels_key(self.label_names, labels)] += amount

    def render(self) -> list[str]:
        """Render the metric in Prometheus exposition format."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        for key in sorted(self._samples):
            labels = dict(zip(self.label_names, key, strict=False))
            lines.append(
                f"{self.name}{_format_labels(labels)} {_format_number(self._samples[key])}"
            )
        return lines


class _HistogramMetric:
    """Simple Prometheus histogram implementation with labels."""

    def __init__(
        self,
        name: str,
        help_text: str,
        *,
        label_names: tuple[str, ...],
        buckets: Iterable[float],
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        normalized_buckets = tuple(sorted(set(float(bucket) for bucket in buckets)))
        if not normalized_buckets or normalized_buckets[-1] != inf:
            normalized_buckets = (*normalized_buckets, inf)
        self.buckets = normalized_buckets
        self._bucket_counts: dict[tuple[str, ...], list[int]] = {}
        self._counts: dict[tuple[str, ...], int] = defaultdict(int)
        self._sums: dict[tuple[str, ...], float] = defaultdict(float)

    def observe(self, value: float, *, labels: Mapping[str, str]) -> None:
        """Add an observation to the histogram."""
        key = _labels_key(self.label_names, labels)
        bucket_counts = self._bucket_counts.setdefault(key, [0] * len(self.buckets))
        normalized_value = max(0.0, float(value))
        for index, bucket in enumerate(self.buckets):
            if normalized_value <= bucket:
                bucket_counts[index] += 1
        self._counts[key] += 1
        self._sums[key] += normalized_value

    def render(self) -> list[str]:
        """Render the metric in Prometheus exposition format."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        for key in sorted(self._counts):
            labels = dict(zip(self.label_names, key, strict=False))
            bucket_counts = self._bucket_counts.get(key, [0] * len(self.buckets))
            for bucket, count in zip(self.buckets, bucket_counts, strict=False):
                lines.append(
                    f"{self.name}_bucket"
                    f"{_format_labels({**labels, 'le': _format_bucket(bucket)})} "
                    f"{count}"
                )
            lines.append(
                f"{self.name}_count{_format_labels(labels)} {self._counts[key]}"
            )
            lines.append(
                f"{self.name}_sum{_format_labels(labels)} "
                f"{_format_number(self._sums[key])}"
            )
        return lines


class PrometheusMetricsSink(ObservabilitySink):
    """Collect Prometheus-compatible counters and histograms."""

    name = "prometheus"

    def __init__(self) -> None:
        request_labels = ("provider", "endpoint", "method", "status_code")
        duration_labels = ("provider", "endpoint", "method")
        error_labels = ("provider", "endpoint", "method", "error_type")

        self._request_total = _CounterMetric(
            "gpt2giga_http_requests_total",
            "Total handled HTTP requests by provider endpoint and status.",
            label_names=request_labels,
        )
        self._request_duration = _HistogramMetric(
            "gpt2giga_http_request_duration_seconds",
            "Handled HTTP request duration in seconds.",
            label_names=duration_labels,
            buckets=_DEFAULT_REQUEST_BUCKETS_SECONDS,
        )
        self._request_errors = _CounterMetric(
            "gpt2giga_http_request_errors_total",
            "Total handled HTTP request errors by provider endpoint and error type.",
            label_names=error_labels,
        )
        self._stream_duration = _HistogramMetric(
            "gpt2giga_http_stream_duration_seconds",
            "Observed SSE stream lifetime in seconds.",
            label_names=duration_labels,
            buckets=_DEFAULT_STREAM_BUCKETS_SECONDS,
        )

    def record_request_event(self, event: Mapping[str, Any]) -> None:
        """Update metrics from a normalized request event."""
        common_labels = {
            "provider": _label_value(event.get("provider")),
            "endpoint": _label_value(event.get("endpoint")),
            "method": _label_value(event.get("method"), default="UNKNOWN").upper(),
        }
        request_labels = {
            **common_labels,
            "status_code": str(_safe_int(event.get("status_code"), default=0)),
        }
        self._request_total.inc(labels=request_labels)
        self._request_duration.observe(
            _ms_to_seconds(event.get("duration_ms")),
            labels=common_labels,
        )

        error_type = _label_value(event.get("error_type"), default="")
        if error_type:
            self._request_errors.inc(
                labels={
                    **common_labels,
                    "error_type": error_type,
                }
            )

        stream_duration = event.get("stream_duration_ms")
        if stream_duration is not None:
            self._stream_duration.observe(
                _ms_to_seconds(stream_duration),
                labels=common_labels,
            )

    def render_prometheus_text(self) -> str:
        """Render the current metrics in Prometheus text format."""
        lines: list[str] = []
        for metric in (
            self._request_total,
            self._request_duration,
            self._request_errors,
            self._stream_duration,
        ):
            lines.extend(metric.render())
        return "\n".join(lines) + "\n"


class ObservabilityHub:
    """Dispatch normalized request events into configured telemetry sinks."""

    def __init__(self, sinks: Mapping[str, ObservabilitySink] | None = None) -> None:
        self._sinks = dict(sinks or {})

    @property
    def enabled_sink_names(self) -> list[str]:
        """Return enabled sink names in stable order."""
        return list(self._sinks)

    async def open(self) -> None:
        """Open all configured sinks."""
        for sink in self._sinks.values():
            await sink.open()

    async def close(self) -> None:
        """Close configured sinks in reverse registration order."""
        for sink in reversed(tuple(self._sinks.values())):
            await sink.close()

    def record_request_event(self, event: Mapping[str, Any]) -> None:
        """Fan out a normalized request event to all sinks."""
        for sink in self._sinks.values():
            sink.record_request_event(event)

    def get_sink(self, name: str) -> ObservabilitySink | None:
        """Return a configured sink by name."""
        return self._sinks.get(name)

    def render_prometheus_text(self) -> str | None:
        """Return the first Prometheus exposition exposed by configured sinks."""
        for sink in self._sinks.values():
            rendered = sink.render_prometheus_text()
            if rendered is not None:
                return rendered
        return None


ObservabilitySinkFactory = Callable[..., ObservabilitySink]


@dataclass(frozen=True, slots=True)
class ObservabilitySinkDescriptor:
    """Describe a pluggable observability sink."""

    name: str
    description: str
    factory: ObservabilitySinkFactory


_OBSERVABILITY_SINKS: dict[str, ObservabilitySinkDescriptor] = {}


def register_observability_sink(descriptor: ObservabilitySinkDescriptor) -> None:
    """Register an observability sink implementation."""
    _OBSERVABILITY_SINKS[descriptor.name] = descriptor


def create_observability_hub(
    names: Iterable[str],
    *,
    config: Any | None = None,
    logger: Any | None = None,
) -> ObservabilityHub:
    """Instantiate an observability hub for the selected sinks."""
    sinks: dict[str, ObservabilitySink] = {}
    for name in names:
        descriptor = _OBSERVABILITY_SINKS.get(name)
        if descriptor is None:
            available = ", ".join(sorted(_OBSERVABILITY_SINKS)) or "<none>"
            raise RuntimeError(
                f"Unsupported observability sink `{name}`. Available: {available}."
            )
        sinks[name] = descriptor.factory(config=config, logger=logger)
    return ObservabilityHub(sinks)


def prometheus_content_type() -> str:
    """Return the Prometheus exposition content type."""
    return _PROMETHEUS_CONTENT_TYPE


def _labels_key(
    label_names: tuple[str, ...], labels: Mapping[str, str]
) -> tuple[str, ...]:
    return tuple(str(labels.get(name, "")) for name in label_names)


def _format_labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    serialized = ",".join(
        f'{key}="{_escape_label_value(value)}"' for key, value in labels.items()
    )
    return f"{{{serialized}}}"


def _escape_label_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_number(value: float) -> str:
    return f"{float(value):g}"


def _format_bucket(value: float) -> str:
    if value == inf:
        return "+Inf"
    return _format_number(value)


def _ms_to_seconds(value: Any) -> float:
    return max(0.0, float(value or 0.0) / 1000.0)


def _label_value(value: Any, *, default: str = "unknown") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_otlp_traces_payload(
    event: Mapping[str, Any],
    *,
    resource_attributes: Mapping[str, Any],
    scope_name: str,
    scope_version: str,
    attribute_enricher: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started_at = _parse_event_started_at(event.get("created_at"))
    duration_ms = max(0.0, float(event.get("duration_ms") or 0.0))
    ended_at = started_at + timedelta(milliseconds=duration_ms)
    span_attributes = _build_otlp_span_attributes(event)
    if attribute_enricher is not None:
        span_attributes.update(attribute_enricher(event))
    error_type = _label_value(event.get("error_type"), default="")
    status_code = _safe_int(event.get("status_code"), default=0)
    span_status = (
        {"code": 2, "message": error_type} if _is_error_event(event) else {"code": 1}
    )
    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    otlp_span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "flags": 1,
        "name": _build_span_name(event),
        "kind": 2,
        "startTimeUnixNano": str(_datetime_to_unix_nanos(started_at)),
        "endTimeUnixNano": str(_datetime_to_unix_nanos(ended_at)),
        "attributes": _serialize_otel_attributes(span_attributes),
        "status": span_status,
    }
    if error_type:
        otlp_span["events"] = [
            {
                "name": "exception",
                "timeUnixNano": otlp_span["endTimeUnixNano"],
                "attributes": _serialize_otel_attributes(
                    {
                        "exception.type": error_type,
                        "exception.message": error_type,
                        "http.response.status_code": status_code,
                    }
                ),
            }
        ]

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _serialize_otel_attributes(resource_attributes),
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": scope_name,
                            "version": scope_version,
                        },
                        "spans": [otlp_span],
                    }
                ],
            }
        ]
    }


def _build_otlp_traces_protobuf_payload(
    event: Mapping[str, Any],
    *,
    resource_attributes: Mapping[str, Any],
    scope_name: str,
    scope_version: str,
    attribute_enricher: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> bytes:
    started_at = _parse_event_started_at(event.get("created_at"))
    duration_ms = max(0.0, float(event.get("duration_ms") or 0.0))
    ended_at = started_at + timedelta(milliseconds=duration_ms)
    span_attributes = _build_otlp_span_attributes(event)
    if attribute_enricher is not None:
        span_attributes.update(attribute_enricher(event))
    error_type = _label_value(event.get("error_type"), default="")
    status_code = _safe_int(event.get("status_code"), default=0)
    end_time_unix_nano = _datetime_to_unix_nanos(ended_at)
    span = Span(
        trace_id=secrets.token_bytes(16),
        span_id=secrets.token_bytes(8),
        flags=1,
        name=_build_span_name(event),
        kind=2,
        start_time_unix_nano=_datetime_to_unix_nanos(started_at),
        end_time_unix_nano=end_time_unix_nano,
        attributes=_serialize_otel_attributes_protobuf(span_attributes),
        status=Status(
            code=2 if _is_error_event(event) else 1,
            message=error_type if _is_error_event(event) else "",
        ),
    )
    if error_type:
        span.events.append(
            Span.Event(
                name="exception",
                time_unix_nano=end_time_unix_nano,
                attributes=_serialize_otel_attributes_protobuf(
                    {
                        "exception.type": error_type,
                        "exception.message": error_type,
                        "http.response.status_code": status_code,
                    }
                ),
            )
        )

    request = ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource=Resource(
                    attributes=_serialize_otel_attributes_protobuf(resource_attributes)
                ),
                scope_spans=[
                    ScopeSpans(
                        scope=InstrumentationScope(
                            name=scope_name,
                            version=scope_version,
                        ),
                        spans=[span],
                    )
                ],
            )
        ]
    )
    return request.SerializeToString()


def _build_otlp_span_attributes(event: Mapping[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "gpt2giga.provider_surface": _label_value(event.get("provider")),
        "gpt2giga.endpoint": _label_value(event.get("endpoint")),
        "http.request.method": _label_value(
            event.get("method"), default="UNKNOWN"
        ).upper(),
        "http.route": _label_value(event.get("endpoint")),
        "http.target": _label_value(event.get("path")),
        "http.response.status_code": _safe_int(event.get("status_code"), default=0),
        "gpt2giga.duration_ms": round(float(event.get("duration_ms") or 0.0), 3),
    }
    if event.get("client_ip"):
        attributes["client.address"] = str(event["client_ip"])
    if event.get("request_id"):
        attributes["gpt2giga.request_id"] = str(event["request_id"])
    if event.get("api_key_name"):
        attributes["gpt2giga.api_key.name"] = str(event["api_key_name"])
    if event.get("api_key_source"):
        attributes["gpt2giga.api_key.source"] = str(event["api_key_source"])
    if event.get("stream_duration_ms") is not None:
        attributes["gpt2giga.stream_duration_ms"] = round(
            float(event["stream_duration_ms"] or 0.0),
            3,
        )

    model = event.get("model")
    if isinstance(model, str) and model:
        attributes["gen_ai.system"] = "gigachat"
        attributes["gen_ai.request.model"] = model

    usage = event.get("token_usage")
    if isinstance(usage, Mapping):
        prompt_tokens = _safe_int(usage.get("prompt_tokens"), default=0)
        completion_tokens = _safe_int(usage.get("completion_tokens"), default=0)
        total_tokens = _safe_int(usage.get("total_tokens"), default=0)
        attributes["gen_ai.usage.input_tokens"] = prompt_tokens
        attributes["gen_ai.usage.output_tokens"] = completion_tokens
        attributes["gen_ai.usage.total_tokens"] = total_tokens

    error_type = _label_value(event.get("error_type"), default="")
    if error_type:
        attributes["error.type"] = error_type
    return attributes


def _build_langfuse_attributes(event: Mapping[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "langfuse.observation.level": "ERROR" if _is_error_event(event) else "DEFAULT",
        "langfuse.observation.metadata.provider_surface": _label_value(
            event.get("provider")
        ),
        "langfuse.observation.metadata.endpoint": _label_value(event.get("endpoint")),
        "langfuse.observation.metadata.status_code": str(
            _safe_int(event.get("status_code"), default=0)
        ),
    }
    method = _label_value(event.get("method"), default="")
    if method:
        attributes["langfuse.observation.metadata.method"] = method.upper()
    request_id = _label_value(event.get("request_id"), default="")
    if request_id:
        attributes["langfuse.observation.metadata.request_id"] = request_id
    api_key_name = _label_value(event.get("api_key_name"), default="")
    if api_key_name:
        attributes["langfuse.observation.metadata.api_key_name"] = api_key_name
    error_type = _label_value(event.get("error_type"), default="")
    if error_type:
        attributes["langfuse.observation.status_message"] = error_type
        attributes["langfuse.observation.metadata.error_type"] = error_type

    model = _label_value(event.get("model"), default="")
    if model:
        attributes["langfuse.observation.type"] = "generation"
        attributes["langfuse.observation.model.name"] = model
    else:
        attributes["langfuse.observation.type"] = "span"

    usage = event.get("token_usage")
    if isinstance(usage, Mapping):
        attributes["langfuse.observation.usage_details"] = json.dumps(
            {
                "input": _safe_int(usage.get("prompt_tokens"), default=0),
                "output": _safe_int(usage.get("completion_tokens"), default=0),
                "total": _safe_int(usage.get("total_tokens"), default=0),
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    return attributes


def _build_default_resource_attributes(config: Any | None) -> dict[str, Any]:
    proxy_settings = getattr(config, "proxy_settings", None)
    service_name = _label_value(
        getattr(proxy_settings, "otlp_service_name", None),
        default="gpt2giga",
    )
    mode = _label_value(getattr(proxy_settings, "mode", None), default="DEV").lower()
    resource_attributes = {
        "service.name": service_name,
        "service.version": _resolve_package_version(),
        "deployment.environment": mode,
    }
    runtime_namespace = _label_value(
        getattr(proxy_settings, "runtime_store_namespace", None),
        default="gpt2giga",
    )
    if runtime_namespace:
        resource_attributes["service.namespace"] = runtime_namespace
    return resource_attributes


def _build_phoenix_resource_attributes(config: Any | None) -> dict[str, Any]:
    resource_attributes = _build_default_resource_attributes(config)
    proxy_settings = getattr(config, "proxy_settings", None)
    project_name = getattr(proxy_settings, "phoenix_project_name", None)
    normalized_project_name = (
        str(project_name).strip() if project_name is not None else ""
    )
    if normalized_project_name:
        resource_attributes["openinference.project.name"] = normalized_project_name
    return resource_attributes


def _build_phoenix_attributes(event: Mapping[str, Any]) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "openinference.span.kind": _resolve_openinference_span_kind(event),
    }
    session_id = _label_value(event.get("session_id"), default="")
    if session_id:
        attributes["session.id"] = session_id
    model = _label_value(event.get("model"), default="")
    if model:
        attributes["llm.model_name"] = model
        attributes["llm.system"] = "gigachat"
        attributes["llm.provider"] = "gigachat"

    input_value = _label_value(event.get("input_value"), default="")
    if input_value:
        attributes["input.value"] = input_value
        input_mime_type = _label_value(event.get("input_mime_type"), default="")
        if input_mime_type:
            attributes["input.mime_type"] = input_mime_type

    output_value = _label_value(event.get("output_value"), default="")
    if output_value:
        attributes["output.value"] = output_value
        output_mime_type = _label_value(event.get("output_mime_type"), default="")
        if output_mime_type:
            attributes["output.mime_type"] = output_mime_type

    _add_phoenix_message_attributes(
        attributes,
        "llm.input_messages",
        event.get("input_messages"),
    )
    _add_phoenix_message_attributes(
        attributes,
        "llm.output_messages",
        event.get("output_messages"),
    )
    _add_phoenix_tools_attributes(attributes, event.get("available_tools"))

    invocation_parameters = _label_value(event.get("invocation_parameters"), default="")
    if invocation_parameters:
        attributes["llm.invocation_parameters"] = invocation_parameters

    usage = event.get("token_usage")
    if isinstance(usage, Mapping):
        attributes["llm.token_count.prompt"] = _safe_int(
            usage.get("prompt_tokens"), default=0
        )
        attributes["llm.token_count.completion"] = _safe_int(
            usage.get("completion_tokens"), default=0
        )
        attributes["llm.token_count.total"] = _safe_int(
            usage.get("total_tokens"), default=0
        )
    return attributes


def _add_phoenix_message_attributes(
    attributes: dict[str, Any],
    prefix: str,
    messages: Any,
) -> None:
    if not isinstance(messages, list):
        return
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            continue
        role = _label_value(message.get("role"), default="")
        content = _label_value(message.get("content"), default="")
        if role:
            attributes[f"{prefix}.{index}.message.role"] = role
        if content:
            attributes[f"{prefix}.{index}.message.content"] = content
        name = _label_value(message.get("name"), default="")
        if name:
            attributes[f"{prefix}.{index}.message.name"] = name
        tool_call_id = _label_value(message.get("tool_call_id"), default="")
        if tool_call_id:
            attributes[f"{prefix}.{index}.message.tool_call_id"] = tool_call_id
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_index, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, Mapping):
                continue
            tool_call_id = _label_value(tool_call.get("id"), default="")
            function_name = _label_value(tool_call.get("function_name"), default="")
            function_arguments = _label_value(
                tool_call.get("function_arguments"),
                default="",
            )
            if tool_call_id:
                attributes[
                    f"{prefix}.{index}.message.tool_calls.{tool_index}.tool_call.id"
                ] = tool_call_id
            if function_name:
                attributes[
                    f"{prefix}.{index}.message.tool_calls.{tool_index}.tool_call.function.name"
                ] = function_name
            if function_arguments:
                attributes[
                    f"{prefix}.{index}.message.tool_calls.{tool_index}.tool_call.function.arguments"
                ] = function_arguments


def _add_phoenix_tools_attributes(
    attributes: dict[str, Any],
    tools: Any,
) -> None:
    if not isinstance(tools, list):
        return
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            continue
        tool_type = _label_value(tool.get("type"), default="")
        if tool_type:
            attributes[f"llm.tools.{index}.tool.type"] = tool_type
        tool_name = _label_value(tool.get("name"), default="")
        if not tool_name and tool_type == "function":
            function = tool.get("function")
            if isinstance(function, Mapping):
                tool_name = _label_value(function.get("name"), default="")
        if tool_name:
            attributes[f"llm.tools.{index}.tool.name"] = tool_name
        tool_schema = json.dumps(tool, ensure_ascii=False, separators=(",", ":"))
        attributes[f"llm.tools.{index}.tool.json_schema"] = tool_schema


def _resolve_openinference_span_kind(event: Mapping[str, Any]) -> str:
    endpoint = _label_value(event.get("endpoint"), default="")
    if "embed" in endpoint:
        return "EMBEDDING"
    if endpoint:
        return "LLM"
    return "UNKNOWN"


def _build_otlp_headers(config: Any | None) -> dict[str, str]:
    proxy_settings = getattr(config, "proxy_settings", None)
    configured = getattr(proxy_settings, "otlp_headers", None)
    if isinstance(configured, Mapping):
        return {
            str(key): str(value)
            for key, value in configured.items()
            if str(key).strip() and value is not None
        }
    return {}


def _resolve_otlp_endpoint(config: Any | None) -> str:
    proxy_settings = getattr(config, "proxy_settings", None)
    endpoint = getattr(proxy_settings, "otlp_traces_endpoint", None)
    normalized = str(endpoint).strip() if endpoint is not None else ""
    if normalized:
        return normalized
    raise RuntimeError(
        "OTLP sink requires GPT2GIGA_OTLP_TRACES_ENDPOINT to be configured."
    )


def _build_langfuse_endpoint(config: Any | None) -> str:
    proxy_settings = getattr(config, "proxy_settings", None)
    base_url = getattr(proxy_settings, "langfuse_base_url", None)
    normalized = str(base_url).strip().rstrip("/") if base_url is not None else ""
    if not normalized:
        raise RuntimeError(
            "Langfuse sink requires GPT2GIGA_LANGFUSE_BASE_URL to be configured."
        )
    return f"{normalized}/api/public/otel/v1/traces"


def _build_langfuse_headers(config: Any | None) -> dict[str, str]:
    proxy_settings = getattr(config, "proxy_settings", None)
    public_key = str(getattr(proxy_settings, "langfuse_public_key", "") or "").strip()
    secret_key = str(getattr(proxy_settings, "langfuse_secret_key", "") or "").strip()
    if not public_key or not secret_key:
        raise RuntimeError(
            "Langfuse sink requires GPT2GIGA_LANGFUSE_PUBLIC_KEY and "
            "GPT2GIGA_LANGFUSE_SECRET_KEY."
        )
    auth_value = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode(
        "ascii"
    )
    headers = {
        "Authorization": f"Basic {auth_value}",
        "x-langfuse-ingestion-version": "4",
    }
    proxy_settings_headers = _build_otlp_headers(config)
    headers.update(proxy_settings_headers)
    return headers


def _build_phoenix_endpoint(config: Any | None) -> str:
    proxy_settings = getattr(config, "proxy_settings", None)
    base_url = getattr(proxy_settings, "phoenix_base_url", None)
    normalized = str(base_url).strip().rstrip("/") if base_url is not None else ""
    if not normalized:
        raise RuntimeError(
            "Phoenix sink requires GPT2GIGA_PHOENIX_BASE_URL to be configured."
        )
    return f"{normalized}/v1/traces"


def _build_phoenix_headers(config: Any | None) -> dict[str, str]:
    proxy_settings = getattr(config, "proxy_settings", None)
    api_key = str(getattr(proxy_settings, "phoenix_api_key", "") or "").strip()
    headers = _build_otlp_headers(config)
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    return headers


def _build_span_name(event: Mapping[str, Any]) -> str:
    method = _label_value(event.get("method"), default="UNKNOWN").upper()
    endpoint = _label_value(event.get("endpoint"), default="/unknown")
    return f"{method} {endpoint}"


def _parse_event_started_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = None
        if isinstance(value, str):
            text = value.strip()
            if text:
                try:
                    parsed = datetime.fromisoformat(text)
                except ValueError:
                    parsed = None
    if parsed is None:
        parsed = datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _datetime_to_unix_nanos(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _serialize_otel_attributes(attributes: Mapping[str, Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for key in sorted(attributes):
        if not str(key).strip():
            continue
        value = attributes[key]
        serialized_value = _serialize_otel_attribute_value(value)
        if serialized_value is None:
            continue
        serialized.append({"key": str(key), "value": serialized_value})
    return serialized


def _serialize_otel_attribute_value(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        values = [
            serialized
            for item in value
            if (serialized := _serialize_otel_attribute_value(item)) is not None
        ]
        return {"arrayValue": {"values": values}}
    return {"stringValue": str(value)}


def _serialize_otel_attributes_protobuf(
    attributes: Mapping[str, Any],
) -> list[KeyValue]:
    serialized: list[KeyValue] = []
    for key in sorted(attributes):
        if not str(key).strip():
            continue
        value = attributes[key]
        serialized_value = _serialize_otel_attribute_value_protobuf(value)
        if serialized_value is None:
            continue
        serialized.append(KeyValue(key=str(key), value=serialized_value))
    return serialized


def _serialize_otel_attribute_value_protobuf(value: Any) -> AnyValue | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return AnyValue(bool_value=value)
    if isinstance(value, int):
        return AnyValue(int_value=value)
    if isinstance(value, float):
        return AnyValue(double_value=value)
    if isinstance(value, (list, tuple)):
        values = [
            serialized
            for item in value
            if (serialized := _serialize_otel_attribute_value_protobuf(item))
            is not None
        ]
        return AnyValue(array_value=ArrayValue(values=values))
    return AnyValue(string_value=str(value))


def _is_error_event(event: Mapping[str, Any]) -> bool:
    return _safe_int(event.get("status_code"), default=0) >= 400 or bool(
        _label_value(event.get("error_type"), default="")
    )


def _resolve_package_version() -> str:
    try:
        return version("gpt2giga")
    except PackageNotFoundError:
        return "dev"


def _log_warning(logger: Any | None, message: str, *args: Any) -> None:
    if logger is None:
        return
    if args:
        try:
            message = message % args
        except (TypeError, ValueError):
            message = " ".join([message, *(str(item) for item in args)])
    warning = getattr(logger, "warning", None)
    if callable(warning):
        warning(message)


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
            max_pending_requests=getattr(
                getattr(kwargs.get("config"), "proxy_settings", None),
                "otlp_max_pending_requests",
                256,
            ),
            timeout_seconds=getattr(
                getattr(kwargs.get("config"), "proxy_settings", None),
                "otlp_timeout_seconds",
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
            max_pending_requests=getattr(
                getattr(kwargs.get("config"), "proxy_settings", None),
                "otlp_max_pending_requests",
                256,
            ),
            timeout_seconds=getattr(
                getattr(kwargs.get("config"), "proxy_settings", None),
                "otlp_timeout_seconds",
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
            max_pending_requests=getattr(
                getattr(kwargs.get("config"), "proxy_settings", None),
                "otlp_max_pending_requests",
                256,
            ),
            timeout_seconds=getattr(
                getattr(kwargs.get("config"), "proxy_settings", None),
                "otlp_timeout_seconds",
                5.0,
            ),
            attribute_enricher=_build_phoenix_attributes,
            content_type=_OTLP_PROTOBUF_TRACES_CONTENT_TYPE,
            payload_builder=_build_otlp_traces_protobuf_payload,
        ),
    )
)
