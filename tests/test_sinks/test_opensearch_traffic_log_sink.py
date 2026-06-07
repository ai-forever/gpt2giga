import json

import pytest

from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.logs.opensearch import (
    OpenSearchTrafficLogSink,
    build_opensearch_bulk_body,
)


class FakeOpenSearchClient:
    def __init__(self, *, fail_times=0, response=None):
        self.fail_times = fail_times
        self.response = response or {"errors": False}
        self.bulk_bodies = []
        self.closed = False

    async def bulk(self, *, body):
        self.bulk_bodies.append(body)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("opensearch unavailable")
        return self.response

    async def close(self):
        self.closed = True


def _event(**overrides):
    values = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "request_id": "req-1",
        "trace_id": "trace-1",
        "protocol": "openai",
        "route": "/v1/chat/completions",
        "method": "POST",
        "status_code": 200,
        "model_requested": "GigaChat",
        "model_effective": "GigaChat-2-Max",
        "provider": "gigachat",
        "latency_ms": 12.7,
        "input_tokens": 3,
        "output_tokens": 5,
        "total_tokens": 8,
        "metadata": {"stream": False},
        "request_headers_redacted": {"authorization": "***"},
    }
    values.update(overrides)
    return TrafficLogEvent(**values)


def test_opensearch_bulk_body_uses_create_for_data_stream():
    body = build_opensearch_bulk_body(
        [_event()],
        index="gpt2giga-traffic",
        data_stream=True,
    )

    lines = [json.loads(line) for line in body.splitlines()]
    assert lines[0] == {
        "create": {
            "_index": "gpt2giga-traffic",
            "_id": "550e8400-e29b-41d4-a716-446655440000",
        }
    }
    assert lines[1]["request_id"] == "req-1"
    assert lines[1]["@timestamp"] == lines[1]["created_at"]
    assert lines[1]["model"] == "GigaChat-2-Max"
    assert lines[1]["has_error"] is False
    assert body.endswith("\n")


def test_opensearch_bulk_body_uses_index_for_plain_index():
    body = build_opensearch_bulk_body(
        [_event(status_code=500, error_type="UpstreamError")],
        index="gpt2giga-traffic",
        data_stream=False,
    )

    lines = [json.loads(line) for line in body.splitlines()]
    assert "index" in lines[0]
    assert lines[1]["has_error"] is True


@pytest.mark.asyncio
async def test_opensearch_sink_writes_batch_and_closes_client():
    client = FakeOpenSearchClient()
    sink = OpenSearchTrafficLogSink(
        "http://opensearch:9200",
        index="gpt2giga-traffic",
        client_factory=lambda: client,
    )

    await sink.emit_many([_event()])
    await sink.flush()

    assert len(client.bulk_bodies) == 1
    assert '"_index":"gpt2giga-traffic"' in client.bulk_bodies[0]
    assert client.closed is True


@pytest.mark.asyncio
async def test_opensearch_sink_retries_before_success():
    client = FakeOpenSearchClient(fail_times=1)
    sink = OpenSearchTrafficLogSink(
        "http://opensearch:9200",
        client_factory=lambda: client,
        max_retries=2,
        retry_backoff_seconds=0,
    )

    await sink.emit_many([_event()])

    assert len(client.bulk_bodies) == 2


@pytest.mark.asyncio
async def test_opensearch_sink_does_not_raise_on_bulk_failure():
    client = FakeOpenSearchClient(fail_times=3)
    sink = OpenSearchTrafficLogSink(
        "http://opensearch:9200",
        client_factory=lambda: client,
        max_retries=1,
        retry_backoff_seconds=0,
    )

    await sink.emit_many([_event()])
    await sink.flush()

    assert len(client.bulk_bodies) == 2
