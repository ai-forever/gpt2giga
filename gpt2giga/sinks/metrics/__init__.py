"""Metrics sink namespace."""

from gpt2giga.sinks.metrics.emission import (
    REQUESTS_TOTAL,
    REQUEST_DURATION_SECONDS,
    STREAM_DISCONNECTS_TOTAL,
    TOKENS_INPUT_TOTAL,
    TOKENS_OUTPUT_TOTAL,
    TRAFFIC_LOG_DROPPED_TOTAL,
    UPSTREAM_DURATION_SECONDS,
    UPSTREAM_ERRORS_TOTAL,
    emit_metrics_from_traffic_event,
    emit_request_metrics,
    refresh_traffic_log_drop_metric,
    wrap_metrics_body_iterator,
)
from gpt2giga.sinks.metrics.factory import (
    create_metrics_sink,
    emit_metric_increment,
    emit_metric_observation,
    flush_metrics_sink,
)
from gpt2giga.sinks.metrics.noop import NoopMetricsSink
from gpt2giga.sinks.metrics.prometheus import (
    CONTENT_TYPE_LATEST,
    METRIC_DEFINITIONS,
    PrometheusMetricsSink,
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "METRIC_DEFINITIONS",
    "NoopMetricsSink",
    "PrometheusMetricsSink",
    "REQUESTS_TOTAL",
    "REQUEST_DURATION_SECONDS",
    "STREAM_DISCONNECTS_TOTAL",
    "TOKENS_INPUT_TOTAL",
    "TOKENS_OUTPUT_TOTAL",
    "TRAFFIC_LOG_DROPPED_TOTAL",
    "UPSTREAM_DURATION_SECONDS",
    "UPSTREAM_ERRORS_TOTAL",
    "create_metrics_sink",
    "emit_metric_increment",
    "emit_metric_observation",
    "emit_metrics_from_traffic_event",
    "emit_request_metrics",
    "flush_metrics_sink",
    "refresh_traffic_log_drop_metric",
    "wrap_metrics_body_iterator",
]
