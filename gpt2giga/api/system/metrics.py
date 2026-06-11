"""Prometheus-compatible metrics endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI
from starlette.responses import PlainTextResponse

from gpt2giga.sinks.metrics.emission import refresh_traffic_log_drop_metric
from gpt2giga.sinks.metrics.prometheus import CONTENT_TYPE_LATEST


def mount_metrics_endpoint(
    app: FastAPI,
    *,
    path: str,
    dependencies: Sequence[Any] | None = None,
) -> None:
    """Mount the configured metrics endpoint on the app."""

    @app.get(
        path,
        include_in_schema=False,
        dependencies=list(dependencies or []),
    )
    async def metrics() -> PlainTextResponse:
        metrics_sink = getattr(app.state, "metrics_sink", None)
        refresh_traffic_log_drop_metric(
            metrics_sink,
            getattr(app.state, "traffic_log_sink", None),
        )
        render = getattr(metrics_sink, "render", None)
        body = render() if callable(render) else ""
        return PlainTextResponse(body, media_type=CONTENT_TYPE_LATEST)
