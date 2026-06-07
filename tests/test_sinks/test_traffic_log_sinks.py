import asyncio
import json

import pytest

from gpt2giga.core.interfaces import TrafficLogSink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.factory import (
    create_traffic_log_sink,
    emit_traffic_log,
    flush_traffic_log_sink,
)
from gpt2giga.sinks.logs.composite import CompositeTrafficLogSink
from gpt2giga.sinks.logs.jsonl import JsonlTrafficLogSink
from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.logs.noop import NoopTrafficLogSink
from gpt2giga.sinks.logs.opensearch import OpenSearchTrafficLogSink
from gpt2giga.sinks.logs.postgres import PostgresTrafficLogSink
from gpt2giga.sinks.logs.queue import QueuedTrafficLogSink


def test_traffic_log_event_is_json_serializable():
    event = TrafficLogEvent(
        request_id="req-1",
        trace_id="trace-1",
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        metadata={"safe": True},
        request_body_redacted={"authorization": "***"},
    )

    payload = event.to_json_dict()

    assert payload["request_id"] == "req-1"
    assert payload["trace_id"] == "trace-1"
    assert isinstance(payload["id"], str)
    assert isinstance(payload["created_at"], str)
    assert "status_code" not in payload
    json.dumps(payload)


@pytest.mark.asyncio
async def test_noop_traffic_log_sink_implements_contract():
    sink = NoopTrafficLogSink()

    assert isinstance(sink, TrafficLogSink)
    await sink.emit({"event": "ignored"})
    await sink.flush()


@pytest.mark.asyncio
async def test_jsonl_traffic_log_sink_writes_one_event(tmp_path):
    path = tmp_path / "traffic.jsonl"
    sink = JsonlTrafficLogSink(path)
    event = TrafficLogEvent(
        request_id="req-1",
        trace_id="trace-1",
        protocol="openai",
        route="/v1/chat/completions",
        method="POST",
        status_code=200,
        latency_ms=12.5,
        input_tokens=3,
        output_tokens=5,
        total_tokens=8,
        response_body_redacted={"choices": []},
    )

    await sink.emit(event)
    await sink.flush()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["request_id"] == "req-1"
    assert payload["created_at"]
    assert payload["status_code"] == 200
    assert payload["response_body_redacted"] == {"choices": []}


def test_traffic_log_factory_defaults_to_noop(tmp_path):
    settings = ProxySettings(traffic_log_jsonl_path=str(tmp_path / "ignored.jsonl"))

    sink = create_traffic_log_sink(settings)

    assert isinstance(sink, NoopTrafficLogSink)


def test_traffic_log_factory_creates_jsonl_when_enabled(tmp_path):
    path = tmp_path / "traffic.jsonl"
    settings = ProxySettings(
        traffic_log_enabled=True,
        traffic_log_sink="jsonl",
        traffic_log_jsonl_path=str(path),
    )

    sink = create_traffic_log_sink(settings)

    assert isinstance(sink, JsonlTrafficLogSink)
    assert sink.path == path


def test_traffic_log_factory_creates_noop_for_postgres_without_dsn():
    settings = ProxySettings(traffic_log_enabled=True, traffic_log_sink="postgres")

    sink = create_traffic_log_sink(settings)

    assert isinstance(sink, NoopTrafficLogSink)


def test_traffic_log_factory_creates_queued_postgres_when_enabled():
    settings = ProxySettings(
        traffic_log_enabled=True,
        traffic_log_sink="postgres",
        traffic_log_postgres_dsn="postgresql://user:pass@localhost:5432/gpt2giga",
        traffic_log_queue_size=5,
        traffic_log_batch_size=2,
        traffic_log_flush_interval_ms=10,
    )

    sink = create_traffic_log_sink(settings)

    assert isinstance(sink, QueuedTrafficLogSink)
    assert isinstance(sink.sink, PostgresTrafficLogSink)
    assert sink.queue_size == 5
    assert sink.batch_size == 2


def test_traffic_log_factory_creates_queued_opensearch_when_enabled():
    settings = ProxySettings(
        traffic_log_enabled=True,
        traffic_log_sink="opensearch",
        opensearch_url="http://opensearch:9200",
        opensearch_username="user",
        opensearch_password="password",
        opensearch_index="gpt2giga-traffic-test",
        opensearch_data_stream=False,
        opensearch_bulk_size=3,
        opensearch_flush_interval_ms=10,
    )

    sink = create_traffic_log_sink(settings)

    assert isinstance(sink, QueuedTrafficLogSink)
    assert isinstance(sink.sink, OpenSearchTrafficLogSink)
    assert sink.sink.url == "http://opensearch:9200"
    assert sink.sink.username == "user"
    assert sink.sink.password == "password"
    assert sink.sink.index == "gpt2giga-traffic-test"
    assert sink.sink.data_stream is False
    assert sink.batch_size == 3
    assert sink.flush_interval_ms == 10


def test_traffic_log_factory_creates_composite_for_multiple_sinks():
    settings = ProxySettings(
        traffic_log_enabled=True,
        traffic_log_sinks=["postgres", "opensearch"],
        traffic_log_postgres_dsn="postgresql://user:pass@localhost:5432/gpt2giga",
        opensearch_url="http://opensearch:9200",
    )

    sink = create_traffic_log_sink(settings)

    assert isinstance(sink, CompositeTrafficLogSink)
    assert len(sink.sinks) == 2
    assert isinstance(sink.sinks[0], QueuedTrafficLogSink)
    assert isinstance(sink.sinks[0].sink, PostgresTrafficLogSink)
    assert isinstance(sink.sinks[1], QueuedTrafficLogSink)
    assert isinstance(sink.sinks[1].sink, OpenSearchTrafficLogSink)


@pytest.mark.asyncio
async def test_traffic_log_safe_helpers_do_not_raise_on_sink_errors():
    class BrokenSink:
        async def emit(self, event):
            raise RuntimeError("emit failed")

        async def flush(self):
            raise RuntimeError("flush failed")

    sink = BrokenSink()

    await emit_traffic_log(sink, {"event": "ignored"})
    await flush_traffic_log_sink(sink)


@pytest.mark.asyncio
async def test_composite_traffic_log_sink_isolates_child_errors():
    class BrokenSink:
        async def emit(self, event):
            raise RuntimeError("emit failed")

        async def flush(self):
            raise RuntimeError("flush failed")

    class RecordingSink:
        def __init__(self):
            self.events = []
            self.flushed = False

        async def emit(self, event):
            self.events.append(event)

        async def flush(self):
            self.flushed = True

    recorder = RecordingSink()
    sink = CompositeTrafficLogSink([BrokenSink(), recorder])

    await sink.emit({"id": 1})
    await sink.flush()

    assert recorder.events == [{"id": 1}]
    assert recorder.flushed is True


@pytest.mark.asyncio
async def test_queued_traffic_log_sink_flushes_batches():
    class RecordingSink:
        def __init__(self):
            self.batches = []
            self.flushed = False

        async def emit_many(self, events):
            self.batches.append(list(events))

        async def flush(self):
            self.flushed = True

    inner = RecordingSink()
    sink = QueuedTrafficLogSink(
        inner, queue_size=10, batch_size=2, flush_interval_ms=10
    )

    await sink.emit({"id": 1})
    await sink.emit({"id": 2})
    await sink.emit({"id": 3})
    await sink.flush()

    assert inner.batches == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
    assert inner.flushed is True
    assert sink.emitted_events == 3


@pytest.mark.asyncio
async def test_queued_traffic_log_sink_drops_on_backpressure():
    release = asyncio.Event()

    class PausedSink:
        async def emit_many(self, events):
            await release.wait()

        async def flush(self):
            return None

    sink = QueuedTrafficLogSink(
        PausedSink(),
        queue_size=1,
        batch_size=1,
        flush_interval_ms=10,
        drop_on_backpressure=True,
    )

    await sink.emit({"id": 1})
    await asyncio.sleep(0)
    await sink.emit({"id": 2})
    await sink.emit({"id": 3})
    release.set()
    await sink.flush()

    assert sink.dropped_events >= 1


@pytest.mark.asyncio
async def test_queued_traffic_log_sink_isolates_inner_errors():
    class BrokenSink:
        async def emit_many(self, events):
            raise RuntimeError("postgres unavailable")

        async def flush(self):
            raise RuntimeError("flush unavailable")

    sink = QueuedTrafficLogSink(BrokenSink(), flush_interval_ms=10)

    await sink.emit({"id": 1})
    await sink.flush()
