"""Traffic log sink namespace."""

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
from gpt2giga.sinks.logs.query import (
    TrafficLogQueryUnavailable,
    UnavailableTrafficLogQueryStore,
    close_traffic_log_query_store,
    create_traffic_log_query_store,
)
from gpt2giga.sinks.logs.queue import QueuedTrafficLogSink
from gpt2giga.sinks.logs.retention import (
    DEFAULT_RETENTION_BATCH_SIZE,
    purge_expired_traffic_logs,
    retention_cutoff,
    start_traffic_log_retention_task,
    stop_traffic_log_retention_task,
)

__all__ = [
    "JsonlTrafficLogSink",
    "NoopTrafficLogSink",
    "CompositeTrafficLogSink",
    "OpenSearchTrafficLogSink",
    "PostgresTrafficLogSink",
    "QueuedTrafficLogSink",
    "DEFAULT_RETENTION_BATCH_SIZE",
    "TrafficLogEvent",
    "TrafficLogQueryUnavailable",
    "UnavailableTrafficLogQueryStore",
    "close_traffic_log_query_store",
    "create_traffic_log_query_store",
    "create_traffic_log_sink",
    "emit_traffic_log",
    "flush_traffic_log_sink",
    "purge_expired_traffic_logs",
    "retention_cutoff",
    "start_traffic_log_retention_task",
    "stop_traffic_log_retention_task",
]
