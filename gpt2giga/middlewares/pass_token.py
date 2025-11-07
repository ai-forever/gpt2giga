from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from typing import Callable

from gpt2giga.utils import pass_token_to_gigachat


class PassTokenMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically pass token from Authorization header to GigaChat client."""

    async def dispatch(self, request: Request, call_next: Callable):
        state = request.app.state
        proxy_config = getattr(state.config, "proxy_settings", None)

        if proxy_config and getattr(proxy_config, "pass_token", False):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "", 1)

                try:
                    state.gigachat_client = pass_token_to_gigachat(
                        state.gigachat_client, token
                    )
                except Exception as e:
                    state.logger.warning(f"Failed to pass token to GigaChat: {e}")

        response = await call_next(request)
        return response
