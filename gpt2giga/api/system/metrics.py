"""Metrics endpoints for operators and Prometheus scrapers."""

from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import Response

from gpt2giga.app.dependencies import get_runtime_observability
from gpt2giga.app.telemetry import prometheus_content_type
from gpt2giga.core.errors import exceptions_handler

metrics_router = APIRouter(tags=["System"])


def build_metrics_response(request: Request) -> Response:
    """Render Prometheus metrics from the configured telemetry hub."""
    hub = get_runtime_observability(request.app.state).hub
    rendered = None if hub is None else hub.render_prometheus_text()
    if rendered is None:
        raise HTTPException(
            status_code=404,
            detail="Prometheus metrics exporter is not enabled.",
        )
    return Response(
        content=rendered,
        media_type=prometheus_content_type(),
    )


@metrics_router.get("/metrics", response_class=Response)
@exceptions_handler
async def metrics(request: Request) -> Response:
    """Expose Prometheus metrics."""
    return build_metrics_response(request)
