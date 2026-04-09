from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from gpt2giga.common.gigachat_auth import create_gigachat_client_for_request


class PassTokenMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically pass token from Authorization header to GigaChat client."""

    async def dispatch(self, request: Request, call_next: Callable):
        state = request.app.state
        proxy_config = getattr(state.config, "proxy_settings", None)

        request.state.gigachat_client = getattr(state, "gigachat_client", None)

        if (
            request.state.gigachat_client is not None
            and proxy_config
            and getattr(proxy_config, "pass_token", False)
        ):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "", 1)

                try:
                    request.state.gigachat_client = create_gigachat_client_for_request(
                        state.config.gigachat_settings, token
                    )
                except Exception as e:
                    state.logger.warning(f"Failed to pass token to GigaChat: {e}")

        response = await call_next(request)
        return response
