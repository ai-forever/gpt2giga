"""Protected traffic log query endpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from gpt2giga.api.admin.access import verify_admin_key
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.core.interfaces import TrafficLogQueryStore
from gpt2giga.sinks.logs.query import TrafficLogQueryUnavailable


MAX_LOG_QUERY_LIMIT = 500
MAX_LOG_EXPORT_LIMIT = 5_000

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
