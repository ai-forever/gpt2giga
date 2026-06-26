"""Optional Postgres traffic log sink."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from gpt2giga.sinks.logs.serialization import traffic_event_to_python_dict

POSTGRES_INSERT_SQL = """
INSERT INTO gpt2giga_traffic_logs (
    id,
    created_at,
    request_id,
    trace_id,
    span_id,
    protocol,
    route,
    method,
    status_code,
    model_requested,
    model_effective,
    provider,
    upstream_status_code,
    latency_ms,
    upstream_latency_ms,
    input_tokens,
    output_tokens,
    total_tokens,
    error_type,
    error_message,
    api_key_hash,
    client_ip_hash,
    metadata,
    request_headers,
    request_body,
    response_body
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
    $14, $15, $16, $17, $18, $19, $20, $21, $22, $23::jsonb,
    $24::jsonb, $25::jsonb, $26::jsonb
)
ON CONFLICT (id) DO NOTHING
"""

POSTGRES_SELECT_COLUMNS = """
    id::text AS id,
    created_at,
    request_id,
    trace_id,
    span_id,
    protocol,
    route,
    method,
    status_code,
    model_requested,
    model_effective,
    provider,
    upstream_status_code,
    latency_ms,
    upstream_latency_ms,
    input_tokens,
    output_tokens,
    total_tokens,
    error_type,
    error_message,
    api_key_hash,
    client_ip_hash,
    metadata,
    request_headers,
    request_body,
    response_body
"""

POSTGRES_COUNT_EXPIRED_SQL = """
SELECT count(*)::bigint
FROM gpt2giga_traffic_logs
WHERE created_at < $1::timestamptz
"""

POSTGRES_DELETE_EXPIRED_BATCH_SQL = """
WITH expired AS (
    SELECT id
    FROM gpt2giga_traffic_logs
    WHERE created_at < $1::timestamptz
    ORDER BY created_at ASC, id ASC
    LIMIT $2
)
DELETE FROM gpt2giga_traffic_logs
WHERE id IN (SELECT id FROM expired)
RETURNING id::text AS id
"""

POSTGRES_REDACT_PAYLOADS_SQL = """
UPDATE gpt2giga_traffic_logs
SET
    request_headers = CASE WHEN $2 THEN NULL ELSE request_headers END,
    request_body = CASE WHEN $3 THEN NULL ELSE request_body END,
    response_body = CASE WHEN $4 THEN NULL ELSE response_body END,
    metadata = metadata || $5::jsonb
WHERE id = $1::uuid
RETURNING
    id::text AS id,
    request_headers IS NULL AS request_headers_redacted,
    request_body IS NULL AS request_body_redacted,
    response_body IS NULL AS response_body_redacted,
    metadata
"""

PoolFactory = Callable[[str], Awaitable[Any]]

_OPERATION_ROUTE_PATTERNS = {
    "chat_completions": ("%/chat/completions",),
    "responses": ("%/responses",),
    "embeddings": ("%/embeddings",),
    "model_info": ("%/model/info",),
    "models": ("%/models", "%/v1beta/models"),
    "messages": ("%/messages",),
    "count_tokens": ("%/messages/count_tokens", "%:countTokens"),
    "generate_content": ("%:generateContent",),
    "stream_generate_content": ("%:streamGenerateContent",),
    "embed_content": ("%:embedContent",),
    "batch_embed_contents": ("%:batchEmbedContents",),
}

_ROUTE_GROUP_OPERATIONS = {
    "chat": ("chat_completions", "generate_content", "stream_generate_content"),
    "responses": ("responses",),
    "embeddings": ("embeddings", "embed_content", "batch_embed_contents"),
    "messages": ("messages", "count_tokens"),
    "models": ("models", "model_info"),
    "system": ("system",),
    "other": ("unknown",),
}


class PostgresTrafficLogSink:
    """Write traffic log events to Postgres using asyncpg."""

    def __init__(
        self,
        dsn: str,
        *,
        pool_factory: PoolFactory | None = None,
        logger: Any | None = None,
    ):
        self.dsn = dsn
        self.pool_factory = pool_factory
        self.logger = logger
        self._pool: Any | None = None

    async def emit(self, event: Any) -> None:
        """Write one traffic log event."""
        await self.emit_many([event])

    async def emit_many(self, events: Sequence[Any]) -> None:
        """Write a batch of traffic log events best effort."""
        if not events:
            return
        try:
            pool = await self._get_pool()
            await pool.executemany(
                POSTGRES_INSERT_SQL,
                [_event_to_row(event) for event in events],
            )
        except Exception as exc:  # pragma: no cover - no-raise path is tested
            if self.logger is not None:
                self.logger.warning("Postgres traffic log write failed: {}", exc)

    async def flush(self) -> None:
        """Close the lazy Postgres pool best effort."""
        if self._pool is None:
            return
        pool = self._pool
        self._pool = None
        close = getattr(pool, "close", None)
        if close is not None:
            await close()

    async def _get_pool(self) -> Any:
        if self._pool is None:
            self._pool = await self._create_pool()
        return self._pool

    async def _create_pool(self) -> Any:
        if self.pool_factory is not None:
            return await self.pool_factory(self.dsn)
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Install gpt2giga with the 'postgres' extra to use Postgres traffic logs."
            ) from exc
        return await asyncpg.create_pool(dsn=self.dsn, min_size=0)


class PostgresTrafficLogQueryStore:
    """Read traffic log events from Postgres using asyncpg."""

    def __init__(
        self,
        dsn: str,
        *,
        pool_factory: PoolFactory | None = None,
        logger: Any | None = None,
    ):
        self.dsn = dsn
        self.pool_factory = pool_factory
        self.logger = logger
        self._pool: Any | None = None

    async def get(self, event_id: str) -> dict[str, Any] | None:
        """Return one traffic log event by id."""
        pool = await self._get_pool()
        row = await pool.fetchrow(
            f"""
            SELECT {POSTGRES_SELECT_COLUMNS}
            FROM gpt2giga_traffic_logs
            WHERE id = $1::uuid
            """,
            event_id,
        )
        if row is None:
            return None
        return _row_to_record(row)

    async def get_by_request_id(self, request_id: str) -> list[dict[str, Any]]:
        """Return traffic log events for a gateway request id."""
        return await self.list(filters={"request_id": request_id})

    async def purge_expired(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        dry_run: bool = True,
        max_batches: int = 1,
    ) -> dict[str, Any]:
        """Delete or count traffic log events older than cutoff."""
        cutoff = _datetime_value(cutoff)
        batch_size = max(1, int(batch_size))
        max_batches = max(1, int(max_batches))
        pool = await self._get_pool()

        if dry_run:
            expired = await pool.fetchval(POSTGRES_COUNT_EXPIRED_SQL, cutoff)
            return {
                "cutoff": cutoff.isoformat(),
                "dry_run": True,
                "expired": int(expired or 0),
                "deleted": 0,
                "batch_size": batch_size,
                "batches": 0,
                "max_batches": max_batches,
                "complete": None,
            }

        deleted = 0
        batches = 0
        complete = False
        for _ in range(max_batches):
            rows = await pool.fetch(
                POSTGRES_DELETE_EXPIRED_BATCH_SQL,
                cutoff,
                batch_size,
            )
            batch_deleted = len(rows)
            deleted += batch_deleted
            batches += 1
            if batch_deleted < batch_size:
                complete = True
                break

        return {
            "cutoff": cutoff.isoformat(),
            "dry_run": False,
            "expired": None,
            "deleted": deleted,
            "batch_size": batch_size,
            "batches": batches,
            "max_batches": max_batches,
            "complete": complete,
        }

    async def redact_payloads(
        self,
        event_id: str,
        *,
        fields: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Clear selected stored payload columns for one event."""
        selected = set(fields)
        pool = await self._get_pool()
        row = await pool.fetchrow(
            POSTGRES_REDACT_PAYLOADS_SQL,
            _uuid_value(event_id),
            "request_headers" in selected,
            "request_body" in selected,
            "response_body" in selected,
            _jsonb(metadata or {}),
        )
        if row is None:
            return None
        payload = dict(row)
        payload["metadata"] = _decode_json(payload.get("metadata"))
        return payload

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return a page of traffic log events."""
        pool = await self._get_pool()
        where_sql, args = _build_where_clause(filters or {})
        limit_arg = len(args) + 1
        offset_arg = len(args) + 2
        rows = await pool.fetch(
            f"""
            SELECT {POSTGRES_SELECT_COLUMNS}
            FROM gpt2giga_traffic_logs
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ${limit_arg} OFFSET ${offset_arg}
            """,
            *args,
            int(limit),
            int(offset),
        )
        return [_row_to_record(row) for row in rows]

    async def flush(self) -> None:
        """Close the lazy Postgres pool best effort."""
        if self._pool is None:
            return
        pool = self._pool
        self._pool = None
        close = getattr(pool, "close", None)
        if close is not None:
            await close()

    async def _get_pool(self) -> Any:
        if self._pool is None:
            self._pool = await self._create_pool()
        return self._pool

    async def _create_pool(self) -> Any:
        if self.pool_factory is not None:
            return await self.pool_factory(self.dsn)
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Install gpt2giga with the 'postgres' extra to query traffic logs."
            ) from exc
        return await asyncpg.create_pool(dsn=self.dsn, min_size=0)


def _event_to_row(event: Any) -> tuple[Any, ...]:
    payload = traffic_event_to_python_dict(event)
    return (
        _uuid_value(payload.get("id")),
        _datetime_value(payload.get("created_at")),
        payload["request_id"],
        payload.get("trace_id"),
        payload.get("span_id"),
        payload["protocol"],
        payload["route"],
        payload["method"],
        payload.get("status_code"),
        payload.get("model_requested"),
        payload.get("model_effective"),
        payload.get("provider"),
        payload.get("upstream_status_code"),
        _int_or_none(payload.get("latency_ms")),
        _int_or_none(payload.get("upstream_latency_ms")),
        payload.get("input_tokens"),
        payload.get("output_tokens"),
        payload.get("total_tokens"),
        payload.get("error_type"),
        payload.get("error_message"),
        payload.get("api_key_hash"),
        payload.get("client_ip_hash"),
        _jsonb(payload.get("metadata", {})),
        _jsonb(_payload_value(payload, "request_headers", "request_headers_redacted")),
        _jsonb(_payload_value(payload, "request_body", "request_body_redacted")),
        _jsonb(_payload_value(payload, "response_body", "response_body_redacted")),
    )


def _payload_value(payload: dict[str, Any], primary: str, fallback: str) -> Any:
    if primary in payload:
        return payload[primary]
    return payload.get(fallback)


def _uuid_value(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _datetime_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _jsonb(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _build_where_clause(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []

    def add(clause: str, value: Any) -> None:
        if value is None:
            return
        args.append(value)
        clauses.append(clause.format(arg=len(args)))

    add("created_at >= ${arg}::timestamptz", filters.get("from"))
    add("created_at <= ${arg}::timestamptz", filters.get("to"))
    add("protocol = ${arg}", filters.get("protocol"))
    add("route = ${arg}", filters.get("route"))
    add("status_code = ${arg}::integer", filters.get("status_code"))
    add("request_id = ${arg}", filters.get("request_id"))
    add("trace_id = ${arg}", filters.get("trace_id"))
    add("api_key_hash = ${arg}", filters.get("api_key_hash"))

    status_class = filters.get("status_class")
    if status_class == "unknown":
        clauses.append("status_code IS NULL")
    elif isinstance(status_class, str) and status_class.endswith("xx"):
        lower = int(status_class[0]) * 100
        clauses.append(f"(status_code >= {lower} AND status_code < {lower + 100})")

    model = filters.get("model")
    if model is not None:
        args.append(model)
        clauses.append(
            f"(model_requested = ${len(args)} OR model_effective = ${len(args)})"
        )

    operation = filters.get("operation")
    if operation is not None:
        _add_metadata_or_route_filter(
            clauses,
            args,
            metadata_key="operation",
            value=operation,
            route_patterns=_operation_route_patterns(str(operation)),
        )

    route_group = filters.get("route_group")
    if route_group is not None:
        _add_metadata_or_route_filter(
            clauses,
            args,
            metadata_key="route_group",
            value=route_group,
            route_patterns=_route_group_patterns(str(route_group)),
        )

    stream = filters.get("stream")
    if isinstance(stream, bool):
        args.append(json.dumps({"stream": stream}))
        clauses.append(f"metadata @> ${len(args)}::jsonb")

    has_error = filters.get("has_error")
    if has_error is True:
        clauses.append("(error_type IS NOT NULL OR status_code >= 400)")
    elif has_error is False:
        clauses.append(
            "(error_type IS NULL AND (status_code IS NULL OR status_code < 400))"
        )

    if not clauses:
        return "", args
    return "WHERE " + " AND ".join(clauses), args


def _add_metadata_or_route_filter(
    clauses: list[str],
    args: list[Any],
    *,
    metadata_key: str,
    value: str,
    route_patterns: Sequence[str],
) -> None:
    args.append(value)
    metadata_clause = f"metadata->>'{metadata_key}' = ${len(args)}"
    route_clauses: list[str] = []
    for pattern in route_patterns:
        args.append(pattern)
        route_clauses.append(f"route LIKE ${len(args)}")
    if route_clauses:
        clauses.append(f"({metadata_clause} OR {' OR '.join(route_clauses)})")
    else:
        clauses.append(metadata_clause)


def _operation_route_patterns(operation: str) -> tuple[str, ...]:
    return _OPERATION_ROUTE_PATTERNS.get(operation, ())


def _route_group_patterns(route_group: str) -> tuple[str, ...]:
    patterns: list[str] = []
    for operation in _ROUTE_GROUP_OPERATIONS.get(route_group, ()):
        patterns.extend(_operation_route_patterns(operation))
    return tuple(dict.fromkeys(patterns))


def _row_to_record(row: Any) -> dict[str, Any]:
    payload = dict(row)
    for key in ("metadata", "request_headers", "request_body", "response_body"):
        payload[key] = _decode_json(payload.get(key))
    if isinstance(payload.get("id"), uuid.UUID):
        payload["id"] = str(payload["id"])
    return payload


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
