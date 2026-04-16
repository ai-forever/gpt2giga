"""Prometheus metrics sink and exposition helpers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from math import inf
from typing import Any

from .contracts import ObservabilitySink
from .utils import _label_value, _safe_int

_PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_DEFAULT_REQUEST_BUCKETS_SECONDS: tuple[float, ...] = (
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
)
_DEFAULT_STREAM_BUCKETS_SECONDS: tuple[float, ...] = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)


class _CounterMetric:
    """Simple Prometheus counter implementation with labels."""

    def __init__(
        self,
        name: str,
        help_text: str,
        *,
        label_names: tuple[str, ...],
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._samples: dict[tuple[str, ...], float] = defaultdict(float)

    def inc(self, *, labels: Mapping[str, str], amount: float = 1.0) -> None:
        """Increment a counter sample."""
        self._samples[_labels_key(self.label_names, labels)] += amount

    def render(self) -> list[str]:
        """Render the metric in Prometheus exposition format."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        for key in sorted(self._samples):
            labels = dict(zip(self.label_names, key, strict=False))
            lines.append(
                f"{self.name}{_format_labels(labels)} {_format_number(self._samples[key])}"
            )
        return lines


class _HistogramMetric:
    """Simple Prometheus histogram implementation with labels."""

    def __init__(
        self,
        name: str,
        help_text: str,
        *,
        label_names: tuple[str, ...],
        buckets: Iterable[float],
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        normalized_buckets = tuple(sorted(set(float(bucket) for bucket in buckets)))
        if not normalized_buckets or normalized_buckets[-1] != inf:
            normalized_buckets = (*normalized_buckets, inf)
        self.buckets = normalized_buckets
        self._bucket_counts: dict[tuple[str, ...], list[int]] = {}
        self._counts: dict[tuple[str, ...], int] = defaultdict(int)
        self._sums: dict[tuple[str, ...], float] = defaultdict(float)

    def observe(self, value: float, *, labels: Mapping[str, str]) -> None:
        """Add an observation to the histogram."""
        key = _labels_key(self.label_names, labels)
        bucket_counts = self._bucket_counts.setdefault(key, [0] * len(self.buckets))
        normalized_value = max(0.0, float(value))
        for index, bucket in enumerate(self.buckets):
            if normalized_value <= bucket:
                bucket_counts[index] += 1
        self._counts[key] += 1
        self._sums[key] += normalized_value

    def render(self) -> list[str]:
        """Render the metric in Prometheus exposition format."""
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        for key in sorted(self._counts):
            labels = dict(zip(self.label_names, key, strict=False))
            bucket_counts = self._bucket_counts.get(key, [0] * len(self.buckets))
            for bucket, count in zip(self.buckets, bucket_counts, strict=False):
                lines.append(
                    f"{self.name}_bucket"
                    f"{_format_labels({**labels, 'le': _format_bucket(bucket)})} "
                    f"{count}"
                )
            lines.append(
                f"{self.name}_count{_format_labels(labels)} {self._counts[key]}"
            )
            lines.append(
                f"{self.name}_sum{_format_labels(labels)} "
                f"{_format_number(self._sums[key])}"
            )
        return lines


class PrometheusMetricsSink(ObservabilitySink):
    """Collect Prometheus-compatible counters and histograms."""

    name = "prometheus"

    def __init__(self) -> None:
        request_labels = ("provider", "endpoint", "method", "status_code")
        duration_labels = ("provider", "endpoint", "method")
        error_labels = ("provider", "endpoint", "method", "error_type")

        self._request_total = _CounterMetric(
            "gpt2giga_http_requests_total",
            "Total handled HTTP requests by provider endpoint and status.",
            label_names=request_labels,
        )
        self._request_duration = _HistogramMetric(
            "gpt2giga_http_request_duration_seconds",
            "Handled HTTP request duration in seconds.",
            label_names=duration_labels,
            buckets=_DEFAULT_REQUEST_BUCKETS_SECONDS,
        )
        self._request_errors = _CounterMetric(
            "gpt2giga_http_request_errors_total",
            "Total handled HTTP request errors by provider endpoint and error type.",
            label_names=error_labels,
        )
        self._stream_duration = _HistogramMetric(
            "gpt2giga_http_stream_duration_seconds",
            "Observed SSE stream lifetime in seconds.",
            label_names=duration_labels,
            buckets=_DEFAULT_STREAM_BUCKETS_SECONDS,
        )

    def record_request_event(self, event: Mapping[str, Any]) -> None:
        """Update metrics from a normalized request event."""
        common_labels = {
            "provider": _label_value(event.get("provider")),
            "endpoint": _label_value(event.get("endpoint")),
            "method": _label_value(event.get("method"), default="UNKNOWN").upper(),
        }
        request_labels = {
            **common_labels,
            "status_code": str(_safe_int(event.get("status_code"), default=0)),
        }
        self._request_total.inc(labels=request_labels)
        self._request_duration.observe(
            _ms_to_seconds(event.get("duration_ms")),
            labels=common_labels,
        )

        error_type = _label_value(event.get("error_type"), default="")
        if error_type:
            self._request_errors.inc(
                labels={
                    **common_labels,
                    "error_type": error_type,
                }
            )

        stream_duration = event.get("stream_duration_ms")
        if stream_duration is not None:
            self._stream_duration.observe(
                _ms_to_seconds(stream_duration),
                labels=common_labels,
            )

    def render_prometheus_text(self) -> str:
        """Render the current metrics in Prometheus text format."""
        lines: list[str] = []
        for metric in (
            self._request_total,
            self._request_duration,
            self._request_errors,
            self._stream_duration,
        ):
            lines.extend(metric.render())
        return "\n".join(lines) + "\n"


def prometheus_content_type() -> str:
    """Return the Prometheus exposition content type."""
    return _PROMETHEUS_CONTENT_TYPE


def _labels_key(
    label_names: tuple[str, ...], labels: Mapping[str, str]
) -> tuple[str, ...]:
    return tuple(str(labels.get(name, "")) for name in label_names)


def _format_labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    serialized = ",".join(
        f'{key}="{_escape_label_value(value)}"' for key, value in labels.items()
    )
    return f"{{{serialized}}}"


def _escape_label_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_number(value: float) -> str:
    return f"{float(value):g}"


def _format_bucket(value: float) -> str:
    if value == inf:
        return "+Inf"
    return _format_number(value)


def _ms_to_seconds(value: Any) -> float:
    return max(0.0, float(value or 0.0) / 1000.0)
