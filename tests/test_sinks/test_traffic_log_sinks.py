import json

import pytest

from gpt2giga.core.interfaces import TrafficLogSink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.factory import (
    create_traffic_log_sink,
    emit_traffic_log,
    flush_traffic_log_sink,
)
from gpt2giga.sinks.logs.jsonl import JsonlTrafficLogSink
from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.logs.noop import NoopTrafficLogSink


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
