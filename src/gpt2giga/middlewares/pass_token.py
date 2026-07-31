from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse

from gpt2giga.providers.gigachat.auth import (
    PassTokenError,
    create_gigachat_client_for_request,
)
from gpt2giga.providers.gigachat.client import GigaChatClientConfigurationError

_PASS_TOKEN_FAILURE_MESSAGE = "Invalid GigaChat pass-through authentication"


class PassTokenMiddleware:
    """Middleware to automatically pass token from Authorization header to GigaChat client."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope["app"].state
        proxy_config = getattr(state.config, "proxy_settings", None)
        scope.setdefault("state", {})["gigachat_client"] = getattr(
            state, "gigachat_client", None
        )

        if not (
            scope["state"]["gigachat_client"] is not None
            and proxy_config
            and getattr(proxy_config, "pass_token", False)
        ):
            await self.app(scope, receive, send)
            return

        token = _bearer_token(scope)
        if token is None:
            await self.app(scope, receive, send)
            return

        pool = getattr(state, "gigachat_pool", None)
        if pool is not None:
            lease = pool.acquire(token)
            try:
                client = await lease.__aenter__()
            except (PassTokenError, GigaChatClientConfigurationError) as exc:
                state.logger.warning("Failed to pass token to GigaChat")
                await _send_pass_token_error(scope, receive, send, str(exc))
                return
            except Exception:
                state.logger.warning("Failed to pass token to GigaChat")
                await _send_pass_token_error(
                    scope, receive, send, _PASS_TOKEN_FAILURE_MESSAGE
                )
                return
            scope["state"]["gigachat_client"] = client
            try:
                await self.app(scope, receive, send)
            finally:
                await lease.__aexit__(None, None, None)
            return

        try:
            client = create_gigachat_client_for_request(
                state.config.gigachat_settings, token
            )
        except (PassTokenError, GigaChatClientConfigurationError) as exc:
            state.logger.warning("Failed to pass token to GigaChat")
            await _send_pass_token_error(scope, receive, send, str(exc))
            return
        except Exception:
            state.logger.warning("Failed to pass token to GigaChat")
            await _send_pass_token_error(
                scope, receive, send, _PASS_TOKEN_FAILURE_MESSAGE
            )
            return

        scope["state"]["gigachat_client"] = client
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                await client.aclose()
            except Exception:  # pragma: no cover - best-effort cleanup
                state.logger.warning("Failed to close request-scoped GigaChat client")


def _bearer_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name.lower() != b"authorization":
            continue
        auth_header = value.decode("latin-1")
        if auth_header.startswith("Bearer "):
            return auth_header.removeprefix("Bearer ")
    return None


async def _send_pass_token_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    message: str,
) -> None:
    response = JSONResponse(status_code=400, content={"detail": message})
    await response(scope, receive, send)
