import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from gpt2giga.core.context import build_request_context, request_context_var
from gpt2giga.logger import logger, rquid_context


class RquidMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware to assign a unique request ID (rquid) to each request.
        """
        rquid = str(uuid.uuid4())
        request_context = build_request_context(request, request_id=rquid)
        token = rquid_context.set(rquid)
        context_token = request_context_var.set(request_context)
        request.state.request_context = request_context

        try:
            response = await call_next(request)
        except Exception:
            logger.bind(
                request_id=request_context.request_id,
                trace_id=request_context.trace_id,
            ).exception("Unhandled exception during request")
            raise
        finally:
            rquid_context.reset(token)
            request_context_var.reset(context_token)

        response.headers["X-Request-ID"] = rquid
        return response
