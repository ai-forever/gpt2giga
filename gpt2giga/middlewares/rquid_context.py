import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from gpt2giga.logger import logger, rquid_context


class RquidMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware to assign a unique request ID (rquid) to each request.
        """
        rquid = str(uuid.uuid4())
        token = rquid_context.set(rquid)

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception("Unhandled exception during request")
            raise exc
        finally:
            rquid_context.reset(token)

        response.headers["X-Request-ID"] = rquid
        return response
