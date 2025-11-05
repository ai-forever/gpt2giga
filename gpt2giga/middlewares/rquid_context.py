import uuid
from urllib.request import Request

from starlette.middleware.base import BaseHTTPMiddleware

from gpt2giga.logger import rquid_context


class RquidMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        """
            Middleware to assign a unique request ID (rquid) to each request.
            """
        rquid = str(uuid.uuid4())
        request.app.state.rquid = rquid
        token = rquid_context.set(rquid)
        try:
            response = await call_next(request)
        except Exception as e:
            request.app.state.logger.exception("Unhandled exception during request", extra={"rquid": rquid})
            raise
        finally:
            rquid_context.reset(token)

        response.headers["X-Request-ID"] = rquid
        return response
