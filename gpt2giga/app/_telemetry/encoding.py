"""Shared OTLP span encoding helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opentelemetry.proto.common.v1.common_pb2 import AnyValue, ArrayValue, KeyValue

from .utils import _label_value, _safe_int


def _build_span_name(event: dict[str, Any] | Any) -> str:
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


def _serialize_otel_attributes(
    attributes: dict[str, Any] | Any,
) -> list[dict[str, Any]]:
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
    attributes: dict[str, Any] | Any,
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


def _is_error_event(event: dict[str, Any] | Any) -> bool:
    return _safe_int(event.get("status_code"), default=0) >= 400 or bool(
        _label_value(event.get("error_type"), default="")
    )
