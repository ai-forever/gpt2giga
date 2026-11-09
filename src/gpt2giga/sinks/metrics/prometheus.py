"""In-process Prometheus-compatible metrics sink."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

MetricLabels = tuple[tuple[str, str], ...]

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
DEFAULT_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)
ALLOWED_LABELS = frozenset(
    {
        "protocol",
        "route",
        "method",
        "status_code",
        "lifecycle",
        "provider",
        "error_type",
        "model",
        "sink",
    }
)
# Unknown model names and exception classes must not create one series per request.
MODEL_LABELS = frozenset(
    {
        "GigaChat",
        "GigaChat-Pro",
        "GigaChat-Max",
        "GigaChat-2",
        "GigaChat-2-Pro",
        "GigaChat-2-Max",
        "Embeddings",
        "EmbeddingsGigaR",
    }
)
ERROR_LABELS = frozenset(
    {
        "stream_cancelled",
        "request_cancelled",
        "HTTPException",
        "TimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ReadError",
        "ConnectError",
        "ResponseError",
        "AuthenticationError",
        "RateLimitError",
        "InternalServerError",
        "BadRequestError",
        "APIConnectionError",
        "APITimeoutError",
        "RuntimeError",
        "ValueError",
    }
)
METRIC_DEFINITIONS: dict[str, tuple[str, str]] = {
    "gpt2giga_requests_total": (
        "counter",
        "Total number of gpt2giga HTTP requests.",
    ),
    "gpt2giga_request_duration_seconds": (
        "histogram",
        "HTTP request duration in seconds.",
    ),
    "gpt2giga_upstream_duration_seconds": (
        "histogram",
        "Upstream provider call duration in seconds.",
    ),
    "gpt2giga_upstream_errors_total": (
        "counter",
        "Total number of upstream provider errors.",
    ),
    "gpt2giga_tokens_input_total": (
        "counter",
        "Total number of input tokens reported by providers.",
    ),
    "gpt2giga_tokens_output_total": (
        "counter",
        "Total number of output tokens reported by providers.",
    ),
    "gpt2giga_stream_disconnects_total": (
        "counter",
        "Total number of streaming requests aborted by client disconnects.",
    ),
    "gpt2giga_traffic_log_dropped_total": (
        "counter",
        "Total number of traffic log events dropped under backpressure.",
    ),
}


@dataclass
class HistogramState:
    """Store cumulative histogram state for one label set."""

    buckets: dict[float, int] = field(default_factory=dict)
    count: int = 0
    total: float = 0.0


class PrometheusMetricsSink:
    """Collect aggregate service metrics and render Prometheus text format."""

    def __init__(
        self,
        buckets: Iterable[float] = DEFAULT_BUCKETS,
        *,
        known_models: Iterable[str] = (),
    ):
        self.buckets = tuple(sorted(float(bucket) for bucket in buckets))
        self.known_models = MODEL_LABELS | frozenset(known_models)
        self._counters: dict[tuple[str, MetricLabels], float] = {}
        self._histograms: dict[tuple[str, MetricLabels], HistogramState] = {}
        self._lock = RLock()

    async def increment(
        self,
        name: str,
        value: int = 1,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Increment a counter metric."""
        if value <= 0:
            return
        labels = normalize_labels(attributes, known_models=self.known_models)
        with self._lock:
            key = (name, labels)
            self._counters[key] = self._counters.get(key, 0.0) + value

    async def observe(
        self,
        name: str,
        value: float,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a histogram observation."""
        if value < 0:
            return
        labels = normalize_labels(attributes, known_models=self.known_models)
        with self._lock:
            state = self._histograms.setdefault(
                (name, labels),
                HistogramState(buckets={bucket: 0 for bucket in self.buckets}),
            )
            state.count += 1
            state.total += value
            for bucket in self.buckets:
                if value <= bucket:
                    state.buckets[bucket] += 1

    def set_counter(
        self,
        name: str,
        value: int,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Set an absolute counter value for externally maintained totals."""
        labels = normalize_labels(attributes, known_models=self.known_models)
        with self._lock:
            self._counters[(name, labels)] = max(float(value), 0.0)

    def render(self) -> str:
        """Render the current metrics in Prometheus text exposition format."""
        with self._lock:
            counters = dict(self._counters)
            histograms = {
                key: HistogramState(
                    buckets=dict(state.buckets),
                    count=state.count,
                    total=state.total,
                )
                for key, state in self._histograms.items()
            }

        lines: list[str] = []
        for name, (metric_type, help_text) in METRIC_DEFINITIONS.items():
            lines.append(f"# HELP {name} {_escape_help(help_text)}")
            lines.append(f"# TYPE {name} {metric_type}")
            if metric_type == "histogram":
                self._render_histogram(lines, name, histograms)
            else:
                self._render_counter(lines, name, counters)
        return "\n".join(lines) + "\n"

    async def flush(self) -> None:
        """Flush no buffered remote metrics."""
        return None

    def _render_counter(
        self,
        lines: list[str],
        name: str,
        counters: dict[tuple[str, MetricLabels], float],
    ) -> None:
        samples = [
            (labels, value)
            for (metric_name, labels), value in sorted(counters.items())
            if metric_name == name
        ]
        if not samples:
            samples = [((), 0.0)]
        for labels, value in samples:
            lines.append(f"{name}{_format_labels(labels)} {_format_number(value)}")

    def _render_histogram(
        self,
        lines: list[str],
        name: str,
        histograms: dict[tuple[str, MetricLabels], HistogramState],
    ) -> None:
        samples = [
            (labels, state)
            for (metric_name, labels), state in sorted(histograms.items())
            if metric_name == name
        ]
        if not samples:
            samples = [
                (
                    (),
                    HistogramState(
                        buckets={bucket: 0 for bucket in self.buckets},
                        count=0,
                        total=0.0,
                    ),
                )
            ]
        for labels, state in samples:
            for bucket in self.buckets:
                bucket_labels = (*labels, ("le", _format_bucket(bucket)))
                lines.append(
                    f"{name}_bucket{_format_labels(bucket_labels)} "
                    f"{state.buckets.get(bucket, 0)}"
                )
            inf_labels = (*labels, ("le", "+Inf"))
            lines.append(f"{name}_bucket{_format_labels(inf_labels)} {state.count}")
            lines.append(f"{name}_sum{_format_labels(labels)} {state.total:.12g}")
            lines.append(f"{name}_count{_format_labels(labels)} {state.count}")


def normalize_labels(
    attributes: Mapping[str, Any] | None,
    *,
    known_models: frozenset[str] = MODEL_LABELS,
) -> MetricLabels:
    """Return whitelisted Prometheus labels without raw content or secrets."""
    if not attributes:
        return ()
    labels = {}
    for key, value in attributes.items():
        if key not in ALLOWED_LABELS or value is None:
            continue
        value = str(value)
        if key == "model" and value not in known_models:
            value = "other"
        elif key == "error_type" and value not in ERROR_LABELS:
            value = "other"
        elif key == "method" and value not in {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "HEAD",
            "OPTIONS",
            "TRACE",
            "CONNECT",
        }:
            value = "other"
        labels[key] = value
    return tuple(sorted(labels.items()))


def _format_labels(labels: MetricLabels) -> str:
    if not labels:
        return ""
    values = ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels)
    return "{" + values + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _escape_help(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _format_bucket(value: float) -> str:
    return f"{value:g}"


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.12g}"
