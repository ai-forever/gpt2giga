"""Traffic log sink namespace."""

from gpt2giga.sinks.logs.factory import (
    create_traffic_log_sink,
    emit_traffic_log,
    flush_traffic_log_sink,
)
from gpt2giga.sinks.logs.jsonl import JsonlTrafficLogSink
from gpt2giga.sinks.logs.models import TrafficLogEvent
from gpt2giga.sinks.logs.noop import NoopTrafficLogSink

__all__ = [
    "JsonlTrafficLogSink",
    "NoopTrafficLogSink",
    "TrafficLogEvent",
    "create_traffic_log_sink",
    "emit_traffic_log",
    "flush_traffic_log_sink",
]
