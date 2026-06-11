import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from gpt2giga.core.context import build_request_context, request_context_var
from gpt2giga.logger import logger, rquid_context
from gpt2giga.sinks.logs.emission import (
    capture_traffic_request_headers,
    emit_request_traffic_event,
    is_streaming_content_type,
    wrap_traffic_log_body_iterator,
)
from gpt2giga.sinks.metrics.emission import (
    emit_request_metrics,
    wrap_metrics_body_iterator,
)
from gpt2giga.sinks.observability.emission import (
    emit_request_observability_event,
    wrap_observability_body_iterator,
)


class RquidMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware to assign a unique request ID (rquid) to each request.
        """
        rquid = str(uuid.uuid4())
        request_context = build_request_context(request, request_id=rquid)
        capture_traffic_request_headers(request, request_context)
        token = rquid_context.set(rquid)
        context_token = request_context_var.set(request_context)
        request.state.request_context = request_context

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.bind(
                request_id=request_context.request_id,
                trace_id=request_context.trace_id,
            ).exception("Unhandled exception during request")
            await emit_request_traffic_event(
                getattr(request.app.state, "traffic_log_sink", None),
                request_context,
                status_code=500,
                lifecycle="request_error",
                logger=getattr(request.app.state, "logger", None),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            await emit_request_observability_event(
                getattr(request.app.state, "observability_sink", None),
                request_context,
                status_code=500,
                lifecycle="request_error",
                logger=getattr(request.app.state, "logger", None),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            await emit_request_metrics(
                getattr(request.app.state, "metrics_sink", None),
                request_context,
                status_code=500,
                lifecycle="request_error",
                logger=getattr(request.app.state, "logger", None),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        finally:
            rquid_context.reset(token)
            request_context_var.reset(context_token)

        response.headers["X-Request-ID"] = rquid
        sink = getattr(request.app.state, "traffic_log_sink", None)
        observability_sink = getattr(request.app.state, "observability_sink", None)
        metrics_sink = getattr(request.app.state, "metrics_sink", None)
        proxy_settings = getattr(
            getattr(request.app.state, "config", None),
            "proxy_settings",
            None,
        )
        content_type = response.headers.get("content-type")
        is_streaming = is_streaming_content_type(content_type)
        if hasattr(response, "body_iterator"):
            response.body_iterator = wrap_metrics_body_iterator(
                wrap_observability_body_iterator(
                    wrap_traffic_log_body_iterator(
                        response.body_iterator,
                        sink=sink,
                        context=request_context,
                        status_code=response.status_code,
                        is_streaming=is_streaming,
                        capture_content=getattr(
                            proxy_settings,
                            "traffic_log_capture_content",
                            False,
                        ),
                        redact_sensitive=getattr(
                            proxy_settings,
                            "traffic_log_redact_sensitive",
                            True,
                        ),
                        redact_extra_keys=getattr(
                            proxy_settings,
                            "traffic_log_redact_extra_keys",
                            None,
                        ),
                        logger=getattr(request.app.state, "logger", None),
                    ),
                    sink=observability_sink,
                    context=request_context,
                    status_code=response.status_code,
                    is_streaming=is_streaming,
                    logger=getattr(request.app.state, "logger", None),
                ),
                sink=metrics_sink,
                context=request_context,
                status_code=response.status_code,
                is_streaming=is_streaming,
                logger=getattr(request.app.state, "logger", None),
            )
        else:
            await emit_request_traffic_event(
                sink,
                request_context,
                status_code=response.status_code,
                lifecycle="request_completed",
                logger=getattr(request.app.state, "logger", None),
            )
            await emit_request_observability_event(
                observability_sink,
                request_context,
                status_code=response.status_code,
                lifecycle="request_completed",
                logger=getattr(request.app.state, "logger", None),
            )
            await emit_request_metrics(
                metrics_sink,
                request_context,
                status_code=response.status_code,
                lifecycle="request_completed",
                logger=getattr(request.app.state, "logger", None),
            )
        return response
