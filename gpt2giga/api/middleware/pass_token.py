from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from gpt2giga.app.dependencies import get_config_from_state, get_logger_from_state
from gpt2giga.providers.gigachat.auth import create_gigachat_client_for_request
from gpt2giga.providers.gigachat.client import get_gigachat_client


class PassTokenMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically pass token from Authorization header to GigaChat client."""

    async def dispatch(self, request: Request, call_next: Callable):
        app_state = request.app.state
        proxy_config = get_config_from_state(app_state).proxy_settings

        request.state.gigachat_client = get_gigachat_client(request)

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
                        get_config_from_state(app_state).gigachat_settings,
                        token,
                    )
                except Exception as e:
                    logger = get_logger_from_state(app_state)
                    if logger is not None:
                        logger.warning(f"Failed to pass token to GigaChat: {e}")

        response = await call_next(request)
        return response
