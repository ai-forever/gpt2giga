"""OTLP sinks and payload builders."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

import aiohttp
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import InstrumentationScope
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans,
    ScopeSpans,
    Span,
    Status,
)

from .contracts import ObservabilitySink
from .encoding import (
    _build_span_name,
    _datetime_to_unix_nanos,
    _is_error_event,
    _parse_event_started_at,
    _serialize_otel_attributes,
    _serialize_otel_attributes_protobuf,
)
from .utils import _label_value, _log_warning, _resolve_package_version, _safe_int

_OTLP_TRACES_CONTENT_TYPE = "application/json"
_OTLP_PROTOBUF_TRACES_CONTENT_TYPE = "application/x-protobuf"
_OTLP_HTTP_OK_STATUSES = {200, 202}
_OTLP_SCOPE_NAME = "gpt2giga.observability"
_OTLP_SCOPE_VERSION = "1.0.0"


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
            self._resource_attributes,
            _OTLP_SCOPE_NAME,
            _OTLP_SCOPE_VERSION,
            self._attribute_enricher,
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


def _build_otlp_traces_payload(
    event: Mapping[str, Any],
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
        kind=Span.SpanKind.Value("SPAN_KIND_SERVER"),
        start_time_unix_nano=_datetime_to_unix_nanos(started_at),
        end_time_unix_nano=end_time_unix_nano,
        attributes=_serialize_otel_attributes_protobuf(span_attributes),
        status=Status(
            code=Status.StatusCode.Value(
                "STATUS_CODE_ERROR" if _is_error_event(event) else "STATUS_CODE_OK"
            ),
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


def _build_default_resource_attributes(config: Any | None) -> dict[str, Any]:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    otlp = getattr(observability, "otlp", None)
    runtime_store = getattr(proxy_settings, "runtime_store", None)
    service_name = _label_value(
        getattr(
            otlp, "service_name", getattr(proxy_settings, "otlp_service_name", None)
        ),
        default="gpt2giga",
    )
    mode = _label_value(getattr(proxy_settings, "mode", None), default="DEV").lower()
    resource_attributes = {
        "service.name": service_name,
        "service.version": _resolve_package_version(),
        "deployment.environment": mode,
    }
    runtime_namespace = _label_value(
        getattr(
            runtime_store,
            "namespace",
            getattr(proxy_settings, "runtime_store_namespace", None),
        ),
        default="gpt2giga",
    )
    if runtime_namespace:
        resource_attributes["service.namespace"] = runtime_namespace
    return resource_attributes


def _build_otlp_headers(config: Any | None) -> dict[str, str]:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    otlp = getattr(observability, "otlp", None)
    configured = getattr(otlp, "headers", getattr(proxy_settings, "otlp_headers", None))
    if isinstance(configured, Mapping):
        return {
            str(key): str(value)
            for key, value in configured.items()
            if str(key).strip() and value is not None
        }
    return {}


def _resolve_otlp_endpoint(config: Any | None) -> str:
    proxy_settings = getattr(config, "proxy_settings", None)
    observability = getattr(proxy_settings, "observability", None)
    otlp = getattr(observability, "otlp", None)
    endpoint = getattr(
        otlp,
        "traces_endpoint",
        getattr(proxy_settings, "otlp_traces_endpoint", None),
    )
    normalized = str(endpoint).strip() if endpoint is not None else ""
    if normalized:
        return normalized
    raise RuntimeError(
        "OTLP sink requires GPT2GIGA_OTLP_TRACES_ENDPOINT to be configured."
    )
