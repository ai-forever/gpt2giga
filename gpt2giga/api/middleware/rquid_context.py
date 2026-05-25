import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gpt2giga.core.logging.setup import logger, rquid_context


class RquidMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Middleware to assign a unique request ID (rquid) to each request.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rquid = str(uuid.uuid4())
        token = rquid_context.set(rquid)

        async def send_with_rquid(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = rquid
            await send(message)

        try:
            await self.app(scope, receive, send_with_rquid)
        except Exception as exc:
            logger.exception("Unhandled exception during request")
            raise exc
        finally:
            rquid_context.reset(token)
