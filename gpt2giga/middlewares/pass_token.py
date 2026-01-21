from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from typing import Callable
from gigachat import GigaChat

from gpt2giga.utils import pass_token_to_gigachat


class PassTokenMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically pass token from Authorization header to GigaChat client."""

    async def dispatch(self, request: Request, call_next: Callable):
        state = request.app.state
        proxy_config = getattr(state.config, "proxy_settings", None)

        request.state.gigachat_client = state.gigachat_client

        if proxy_config and getattr(proxy_config, "pass_token", False):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "", 1)

                try:
                    new_client = GigaChat(**state.config.gigachat_settings.model_dump())
                    request.state.gigachat_client = pass_token_to_gigachat(
                        new_client, token
                    )
                except Exception as e:
                    state.logger.warning(f"Failed to pass token to GigaChat: {e}")

        response = await call_next(request)
        return response
