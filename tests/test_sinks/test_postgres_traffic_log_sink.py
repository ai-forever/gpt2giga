import json

import pytest

from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.logs.postgres import PostgresTrafficLogSink


class FakePool:
    def __init__(self):
        self.executed = []
        self.closed = False

    async def executemany(self, sql, rows):
        self.executed.append((sql, rows))

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_postgres_sink_does_not_raise_on_pool_failure():
    async def pool_factory(dsn):
        raise RuntimeError("database unavailable")

    sink = PostgresTrafficLogSink("postgresql://example", pool_factory=pool_factory)

    await sink.emit({"request_id": "req-1"})
    await sink.flush()
