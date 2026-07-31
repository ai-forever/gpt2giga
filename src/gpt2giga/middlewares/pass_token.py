from starlette.types import ASGIApp, Receive, Scope, Send

from gpt2giga.providers.gigachat.auth import create_gigachat_client_for_request


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
            except Exception as exc:
                state.logger.warning(f"Failed to pass token to GigaChat: {exc}")
                await self.app(scope, receive, send)
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
        except Exception as exc:
            state.logger.warning(f"Failed to pass token to GigaChat: {exc}")
            await self.app(scope, receive, send)
            return

        scope["state"]["gigachat_client"] = client
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                await client.aclose()
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                state.logger.warning(
                    f"Failed to close request-scoped GigaChat client: {exc}"
                )


def _bearer_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name.lower() != b"authorization":
            continue
        auth_header = value.decode("latin-1")
        if auth_header.startswith("Bearer "):
            return auth_header.removeprefix("Bearer ")
    return None
