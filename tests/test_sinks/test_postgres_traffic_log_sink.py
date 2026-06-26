import json
from datetime import datetime, timezone


from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.logs.postgres import (
    PostgresTrafficLogQueryStore,
    PostgresTrafficLogSink,
)


class FakePool:
    def __init__(self):
        self.executed = []
        self.fetched = []
        self.fetchval_calls = []
        self.fetchrow_calls = []
        self.closed = False

    async def executemany(self, sql, rows):
        self.executed.append((sql, rows))

    async def fetch(self, sql, *args):
        self.fetched.append((sql, args))
        return [
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "created_at": "2026-06-07T12:00:00+00:00",
                "request_id": "req-1",
                "trace_id": "trace-1",
                "span_id": None,
                "protocol": "openai",
                "route": "/v1/chat/completions",
                "method": "POST",
                "status_code": 200,
                "model_requested": "GigaChat",
                "model_effective": "GigaChat",
                "provider": "gigachat",
                "upstream_status_code": None,
                "latency_ms": 10,
                "upstream_latency_ms": None,
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "error_type": None,
                "error_message": None,
                "api_key_hash": "hash-1",
                "client_ip_hash": None,
                "metadata": '{"stream": false}',
                "request_headers": '{"authorization": "***"}',
                "request_body": None,
                "response_body": '{"ok": true}',
            }
        ]

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        rows = await self.fetch(sql, *args)
        return rows[0]

    async def fetchval(self, sql, *args):
        self.fetchval_calls.append((sql, args))
        return 42

    async def close(self):
        self.closed = True


async def test_postgres_sink_writes_event_batch():
    pool = FakePool()

    async def pool_factory(dsn):
        assert dsn == "postgresql://example"
        return pool

    sink = PostgresTrafficLogSink("postgresql://example", pool_factory=pool_factory)
    event = TrafficLogEvent(
        request_id="req-1",
        trace_id="trace-1",
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        status_code=200,
        latency_ms=12.7,
        upstream_latency_ms=10.2,
        input_tokens=3,
        output_tokens=5,
        total_tokens=8,
        metadata={"model": "GigaChat"},
        request_body_redacted={"messages": []},
        response_body_redacted={"choices": []},
    )

    await sink.emit_many([event])
    await sink.flush()

    assert pool.closed is True
    assert len(pool.executed) == 1
    sql, rows = pool.executed[0]
    assert "insert into gpt2giga_traffic_logs" in sql.lower()
    assert len(rows) == 1
    row = rows[0]
    assert row[2] == "req-1"
    assert row[13] == 13
    assert row[14] == 10
    assert json.loads(row[22]) == {"model": "GigaChat"}
    assert json.loads(row[24]) == {"messages": []}
    assert json.loads(row[25]) == {"choices": []}


async def test_postgres_sink_does_not_raise_on_pool_failure():
    async def pool_factory(dsn):
        raise RuntimeError("database unavailable")

    sink = PostgresTrafficLogSink("postgresql://example", pool_factory=pool_factory)

    await sink.emit({"request_id": "req-1"})
    await sink.flush()


async def test_postgres_query_store_lists_with_filters_and_decodes_json():
    pool = FakePool()

    async def pool_factory(dsn):
        assert dsn == "postgresql://example"
        return pool

    store = PostgresTrafficLogQueryStore(
        "postgresql://example",
        pool_factory=pool_factory,
    )

    records = await store.list(
        limit=2,
        offset=10,
        filters={
            "from": "2026-06-07T00:00:00Z",
            "to": "2026-06-08T00:00:00Z",
            "protocol": "openai",
            "route": "/v1/chat/completions",
            "status_code": 200,
            "request_id": "req-1",
            "trace_id": "trace-1",
            "api_key_hash": "hash-1",
            "model": "GigaChat",
            "has_error": False,
        },
    )
    await store.flush()

    assert pool.closed is True
    assert records[0]["metadata"] == {"stream": False}
    assert records[0]["request_headers"] == {"authorization": "***"}
    assert records[0]["response_body"] == {"ok": True}
    sql, args = pool.fetched[0]
    assert "created_at >= $1::timestamptz" in sql
    assert "created_at <= $2::timestamptz" in sql
    assert "protocol = $3" in sql
    assert "(model_requested = $9 OR model_effective = $9)" in sql
    assert "(error_type IS NULL AND (status_code IS NULL OR status_code < 400))" in sql
    assert args == (
        "2026-06-07T00:00:00Z",
        "2026-06-08T00:00:00Z",
        "openai",
        "/v1/chat/completions",
        200,
        "req-1",
        "trace-1",
        "hash-1",
        "GigaChat",
        2,
        10,
    )


async def test_postgres_query_store_supports_logs_ui_filters():
    pool = FakePool()

    async def pool_factory(dsn):
        return pool

    store = PostgresTrafficLogQueryStore(
        "postgresql://example",
        pool_factory=pool_factory,
    )

    await store.list(
        filters={
            "operation": "chat_completions",
            "route_group": "chat",
            "status_class": "2xx",
            "stream": True,
        }
    )

    sql, args = pool.fetched[0]
    assert "(status_code >= 200 AND status_code < 300)" in sql
    assert "metadata->>'operation' = $1" in sql
    assert "route LIKE $2" in sql
    assert "metadata->>'route_group' = $3" in sql
    assert "metadata @> $7::jsonb" in sql
    assert args == (
        "chat_completions",
        "%/chat/completions",
        "chat",
        "%/chat/completions",
        "%:generateContent",
        "%:streamGenerateContent",
        '{"stream": true}',
        100,
        0,
    )


async def test_postgres_query_store_gets_by_id():
    pool = FakePool()

    async def pool_factory(dsn):
        return pool

    store = PostgresTrafficLogQueryStore(
        "postgresql://example",
        pool_factory=pool_factory,
    )

    record = await store.get("550e8400-e29b-41d4-a716-446655440000")

    assert record["id"] == "550e8400-e29b-41d4-a716-446655440000"
    sql, args = pool.fetchrow_calls[0]
    assert "WHERE id = $1::uuid" in sql
    assert args == ("550e8400-e29b-41d4-a716-446655440000",)


async def test_postgres_query_store_purge_expired_dry_run_counts_by_created_at():
    pool = FakePool()

    async def pool_factory(dsn):
        return pool

    store = PostgresTrafficLogQueryStore(
        "postgresql://example",
        pool_factory=pool_factory,
    )
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)

    result = await store.purge_expired(
        cutoff=cutoff,
        batch_size=100,
        dry_run=True,
        max_batches=5,
    )

    assert result == {
        "cutoff": "2026-06-01T00:00:00+00:00",
        "dry_run": True,
        "expired": 42,
        "deleted": 0,
        "batch_size": 100,
        "batches": 0,
        "max_batches": 5,
        "complete": None,
    }
    sql, args = pool.fetchval_calls[0]
    assert "created_at < $1::timestamptz" in sql
    assert args == (cutoff,)


async def test_postgres_query_store_purge_expired_deletes_bounded_batch():
    pool = FakePool()

    async def pool_factory(dsn):
        return pool

    store = PostgresTrafficLogQueryStore(
        "postgresql://example",
        pool_factory=pool_factory,
    )
    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)

    result = await store.purge_expired(
        cutoff=cutoff,
        batch_size=100,
        dry_run=False,
        max_batches=1,
    )

    assert result["deleted"] == 1
    assert result["batch_size"] == 100
    assert result["batches"] == 1
    assert result["complete"] is True
    sql, args = pool.fetched[0]
    assert "WITH expired AS" in sql
    assert "WHERE created_at < $1::timestamptz" in sql
    assert "ORDER BY created_at ASC, id ASC" in sql
    assert "LIMIT $2" in sql
    assert args == (cutoff, 100)


async def test_postgres_query_store_redacts_payload_columns():
    class RedactPool(FakePool):
        async def fetchrow(self, sql, *args):
            self.fetchrow_calls.append((sql, args))
            return {
                "id": str(args[0]),
                "request_headers_redacted": args[1],
                "request_body_redacted": args[2],
                "response_body_redacted": args[3],
                "metadata": args[4],
            }

    pool = RedactPool()

    async def pool_factory(dsn):
        return pool

    store = PostgresTrafficLogQueryStore(
        "postgresql://example",
        pool_factory=pool_factory,
    )

    result = await store.redact_payloads(
        "550e8400-e29b-41d4-a716-446655440000",
        fields=["request_body"],
        metadata={"manual_redaction": {"fields": ["request_body"]}},
    )

    assert result == {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "request_headers_redacted": False,
        "request_body_redacted": True,
        "response_body_redacted": False,
        "metadata": {"manual_redaction": {"fields": ["request_body"]}},
    }
    sql, args = pool.fetchrow_calls[0]
    assert "UPDATE gpt2giga_traffic_logs" in sql
    assert "request_headers = CASE WHEN $2 THEN NULL ELSE request_headers END" in sql
    assert "request_body = CASE WHEN $3 THEN NULL ELSE request_body END" in sql
    assert "response_body = CASE WHEN $4 THEN NULL ELSE response_body END" in sql
    assert args[1:4] == (False, True, False)
