"""Optional Postgres traffic log sink."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
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

PoolFactory = Callable[[str], Awaitable[Any]]


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
