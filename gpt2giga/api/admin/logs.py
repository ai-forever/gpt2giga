"""Protected traffic log query endpoints."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from gpt2giga.api.admin.access import verify_admin_key
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.core.interfaces import TrafficLogQueryStore
from gpt2giga.core.redaction import redact_traffic_payload
from gpt2giga.sinks.logs.query import TrafficLogQueryUnavailable
from gpt2giga.sinks.logs.retention import (
    DEFAULT_RETENTION_BATCH_SIZE,
    purge_expired_traffic_logs,
    retention_cutoff,
)


MAX_LOG_QUERY_LIMIT = 500
MAX_LOG_EXPORT_LIMIT = 5_000
MAX_RETENTION_BATCH_SIZE = 10_000
MAX_RETENTION_BATCHES = 1_000
BLOCKED_REPLAY_PREFIXES = ("/_admin", "/_debug", "/logs")
MANUAL_REDACTION_FIELDS = frozenset(
    {"request_headers", "request_body", "response_body"}
)
CSV_EXPORT_COLUMNS = [
    "id",
    "created_at",
    "request_id",
    "trace_id",
    "span_id",
    "protocol",
    "route",
    "method",
    "status_code",
    "model_requested",
    "model_effective",
    "provider",
    "upstream_status_code",
    "latency_ms",
    "upstream_latency_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "error_type",
    "api_key_hash",
    "has_request_body",
    "has_response_body",
]

router = APIRouter(
    prefix="/_admin/logs",
    tags=["Admin"],
    dependencies=[Depends(verify_admin_key)],
)


@router.get("")
@exceptions_handler
async def list_logs(
    request: Request,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    protocol: str | None = None,
    route: str | None = None,
    model: str | None = None,
    status_code: int | None = None,
    has_error: bool | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    api_key_hash: str | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_LOG_QUERY_LIMIT),
    cursor: str | None = None,
):
    """List traffic log events with offset-cursor pagination."""
    offset = _parse_cursor(cursor)
    filters = _build_filters(
        from_=from_,
        to=to,
        protocol=protocol,
        route=route,
        model=model,
        status_code=status_code,
        has_error=has_error,
        request_id=request_id,
        trace_id=trace_id,
        api_key_hash=api_key_hash,
    )
    records = await _list_records(
        _get_query_store(request),
        limit=limit,
        offset=offset,
        filters=filters,
    )
    data = [_summary_record(record) for record in records]
    return {
        "data": data,
        "limit": limit,
        "cursor": cursor,
        "next_cursor": str(offset + len(data)) if len(data) == limit else None,
    }


@router.get("/tail")
@exceptions_handler
async def tail_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=MAX_LOG_QUERY_LIMIT),
):
    """Return the most recent traffic log events."""
    records = await _list_records(
        _get_query_store(request),
        limit=limit,
        offset=0,
        filters={},
    )
    return {"data": [_summary_record(record) for record in records], "limit": limit}


@router.get("/export.ndjson")
@exceptions_handler
async def export_logs_ndjson(
    request: Request,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    protocol: str | None = None,
    route: str | None = None,
    model: str | None = None,
    status_code: int | None = None,
    has_error: bool | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    api_key_hash: str | None = None,
    limit: int = Query(default=1_000, ge=1, le=MAX_LOG_EXPORT_LIMIT),
    cursor: str | None = None,
):
    """Export a basic NDJSON page of traffic log events."""
    offset = _parse_cursor(cursor)
    records = await _list_records(
        _get_query_store(request),
        limit=limit,
        offset=offset,
        filters=_build_filters(
            from_=from_,
            to=to,
            protocol=protocol,
            route=route,
            model=model,
            status_code=status_code,
            has_error=has_error,
            request_id=request_id,
            trace_id=trace_id,
            api_key_hash=api_key_hash,
        ),
    )
    payload = "".join(
        json.dumps(_json_ready(record), ensure_ascii=False, default=str) + "\n"
        for record in records
    )
    return PlainTextResponse(payload, media_type="application/x-ndjson")


@router.get("/export.csv")
@exceptions_handler
async def export_logs_csv(
    request: Request,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    protocol: str | None = None,
    route: str | None = None,
    model: str | None = None,
    status_code: int | None = None,
    has_error: bool | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    api_key_hash: str | None = None,
    limit: int = Query(default=1_000, ge=1, le=MAX_LOG_EXPORT_LIMIT),
    cursor: str | None = None,
):
    """Export a CSV page of traffic log summaries without stored payload bodies."""
    offset = _parse_cursor(cursor)
    records = await _list_records(
        _get_query_store(request),
        limit=limit,
        offset=offset,
        filters=_build_filters(
            from_=from_,
            to=to,
            protocol=protocol,
            route=route,
            model=model,
            status_code=status_code,
            has_error=has_error,
            request_id=request_id,
            trace_id=trace_id,
            api_key_hash=api_key_hash,
        ),
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=CSV_EXPORT_COLUMNS, extrasaction="ignore"
    )
    writer.writeheader()
    for record in records:
        writer.writerow(_csv_ready(_summary_record(record)))
    return PlainTextResponse(output.getvalue(), media_type="text/csv")


@router.post("/retention/purge")
@exceptions_handler
async def purge_retained_logs(
    request: Request,
    retention_days: int | None = Query(default=None, ge=1, le=3_650),
    batch_size: int = Query(
        default=DEFAULT_RETENTION_BATCH_SIZE,
        ge=1,
        le=MAX_RETENTION_BATCH_SIZE,
    ),
    max_batches: int = Query(default=1, ge=1, le=MAX_RETENTION_BATCHES),
    dry_run: bool = True,
):
    """Count or delete expired traffic log rows in bounded batches."""
    settings = request.app.state.config.proxy_settings
    effective_retention_days = retention_days or settings.traffic_log_retention_days
    cutoff = retention_cutoff(effective_retention_days)
    try:
        result = await purge_expired_traffic_logs(
            _get_query_store(request),
            cutoff=cutoff,
            batch_size=batch_size,
            dry_run=dry_run,
            max_batches=max_batches,
        )
    except TrafficLogQueryUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return {
        "retention_days": effective_retention_days,
        **_json_ready(dict(result)),
    }


@router.post("/{event_id}/replay")
@exceptions_handler
async def replay_log_request(event_id: str, request: Request):
    """Replay a captured traffic log request through the local gateway app."""
    settings = request.app.state.config.proxy_settings
    if not settings.replay_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    record = await _get_record(_get_query_store(request), event_id)
    method = str(record.get("method") or "").upper()
    route = str(record.get("route") or "")
    if method != "POST":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only POST traffic log requests can be replayed",
        )
    path, query_string = _safe_replay_path(route)
    body = _prepare_replay_body(record)
    response = await _dispatch_replay_request(
        request,
        method=method,
        path=path,
        query_string=query_string,
        body=body,
    )
    return {
        "id": record.get("id"),
        "request_id": record.get("request_id"),
        "replayed": True,
        "request": {
            "method": method,
            "path": path,
            "metadata": body.get("metadata"),
        },
        "response": response,
    }


@router.post("/{event_id}/redact")
@exceptions_handler
async def redact_log_payloads(event_id: str, request: Request):
    """Manually clear stored payload columns for one traffic log event."""
    _validate_event_id(event_id)
    payload = await _read_optional_json_object(request)
    fields = _parse_manual_redaction_fields(payload)
    metadata = {
        "manual_redaction": {
            "fields": sorted(fields),
            "redacted_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    try:
        result = await _get_query_store(request).redact_payloads(
            event_id,
            fields=sorted(fields),
            metadata=metadata,
        )
    except TrafficLogQueryUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Traffic log event not found",
        )
    return {
        "id": event_id,
        "redacted_fields": sorted(fields),
        "result": _json_ready(dict(result)),
    }


@router.get("/{event_id}")
@exceptions_handler
async def get_log(event_id: str, request: Request):
    """Return one traffic log event summary by id."""
    record = await _get_record(_get_query_store(request), event_id)
    return _summary_record(record)


@router.get("/{event_id}/request")
@exceptions_handler
async def get_log_request(event_id: str, request: Request):
    """Return stored redacted request headers/body for one traffic log event."""
    record = await _get_record(_get_query_store(request), event_id)
    return {
        "id": record.get("id"),
        "request_headers": record.get("request_headers"),
        "request_body": record.get("request_body"),
    }


@router.get("/{event_id}/response")
@exceptions_handler
async def get_log_response(event_id: str, request: Request):
    """Return stored redacted response body for one traffic log event."""
    record = await _get_record(_get_query_store(request), event_id)
    return {
        "id": record.get("id"),
        "response_body": record.get("response_body"),
    }


def _get_query_store(request: Request) -> TrafficLogQueryStore:
    store = getattr(request.app.state, "traffic_log_query_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Traffic log query store is not configured",
        )
    return store


async def _list_records(
    store: TrafficLogQueryStore,
    *,
    limit: int,
    offset: int,
    filters: Mapping[str, Any],
) -> Sequence[Mapping[str, Any]]:
    try:
        return await store.list(limit=limit, offset=offset, filters=filters)
    except TrafficLogQueryUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


async def _get_record(
    store: TrafficLogQueryStore,
    event_id: str,
) -> Mapping[str, Any]:
    _validate_event_id(event_id)
    try:
        record = await store.get(event_id)
    except TrafficLogQueryUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Traffic log event not found",
        )
    return record


def _build_filters(
    *,
    from_: str | None,
    to: str | None,
    protocol: str | None,
    route: str | None,
    model: str | None,
    status_code: int | None,
    has_error: bool | None,
    request_id: str | None,
    trace_id: str | None,
    api_key_hash: str | None,
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "from": from_,
            "to": to,
            "protocol": protocol,
            "route": route,
            "model": model,
            "status_code": status_code,
            "has_error": has_error,
            "request_id": request_id,
            "trace_id": trace_id,
            "api_key_hash": api_key_hash,
        }.items()
        if value is not None and value != ""
    }


def _parse_cursor(cursor: str | None) -> int:
    if cursor is None or cursor == "":
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cursor",
        ) from exc
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cursor",
        )
    return offset


def _validate_event_id(event_id: str) -> None:
    try:
        UUID(event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid traffic log id",
        ) from exc


async def _read_optional_json_object(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        return {}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected JSON object body",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected JSON object body",
        )
    return payload


def _parse_manual_redaction_fields(payload: Mapping[str, Any]) -> frozenset[str]:
    fields = payload.get("fields")
    if fields is None:
        return MANUAL_REDACTION_FIELDS
    if not isinstance(fields, list) or not all(
        isinstance(field, str) for field in fields
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected fields to be a list of payload field names",
        )
    selected = frozenset(fields)
    unknown = selected - MANUAL_REDACTION_FIELDS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported redaction fields: {', '.join(sorted(unknown))}",
        )
    if not selected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one redaction field is required",
        )
    return selected


def _safe_replay_path(route: str) -> tuple[str, bytes]:
    parsed = urlsplit(route)
    path = parsed.path or route
    if not path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid replay route",
        )
    if path.startswith(BLOCKED_REPLAY_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin, debug, and log routes cannot be replayed",
        )
    return path, parsed.query.encode()


def _prepare_replay_body(record: Mapping[str, Any]) -> dict[str, Any]:
    request_body = record.get("request_body")
    if not isinstance(request_body, Mapping):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Traffic log request body was not captured",
        )
    body = redact_traffic_payload(dict(request_body))
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Traffic log request body cannot be replayed",
        )
    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    body["metadata"] = {
        **metadata,
        "gpt2giga_replay": {
            "source_log_id": record.get("id"),
            "source_request_id": record.get("request_id"),
            "replayed_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return body


async def _dispatch_replay_request(
    request: Request,
    *,
    method: str,
    path: str,
    query_string: bytes,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False, default=str).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"x-gpt2giga-replay", b"true"),
    ]
    settings = request.app.state.config.proxy_settings
    if settings.enable_api_key_auth and settings.api_key:
        headers.append((b"authorization", f"Bearer {settings.api_key}".encode()))

    messages = [{"type": "http.request", "body": payload, "more_body": False}]
    response: dict[str, Any] = {"status_code": 500, "headers": {}, "body": None}
    chunks: list[bytes] = []

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            response["status_code"] = int(message["status"])
            response["headers"] = {
                key.decode("latin-1"): value.decode("latin-1")
                for key, value in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("gpt2giga-replay", 80),
        "root_path": "",
    }
    try:
        await request.app(scope, receive, send)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Replay request failed",
        ) from exc
    raw_body = b"".join(chunks)
    response["headers"] = redact_traffic_payload(response["headers"])
    response["body"] = _decode_replay_response_body(raw_body)
    return response


def _decode_replay_response_body(raw_body: bytes) -> Any:
    if not raw_body:
        return None
    text = raw_body.decode(errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _summary_record(record: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        key: value
        for key, value in record.items()
        if key not in {"request_headers", "request_body", "response_body"}
    }
    summary["has_request_body"] = record.get("request_body") is not None
    summary["has_response_body"] = record.get("response_body") is not None
    return _json_ready(summary)


def _json_ready(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in record.items()
    }


def _csv_ready(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in record.items()
        if key in CSV_EXPORT_COLUMNS
    }
