from starlette.types import ASGIApp, Receive, Scope, Send

from gpt2giga.core.paths import normalize_api_path


class PathNormalizationMiddleware:
    """
    Redirects any path that contains a known valid segment
    (like /v1/, /models/ etc. ) after some extra unnecessary prefixes.
    """

    def __init__(self, app: ASGIApp, valid_roots=None):
        self.app = app
        # Valid entrypoints
        self.valid_roots = valid_roots or [
            "v1",
            "v2",
            "v1beta",
            "upload",
            "chat",
            "models",
            "embeddings",
            "messages",
            "responses",
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        new_path = self._normalize_path(path)
        if new_path is not None:
            # IMPORTANT:
            # Do not redirect (307) here: some clients may re-issue the request
            # without the original body, which leads to JSONDecodeError in
            # downstream handlers. Instead, rewrite the ASGI scope path in-place.
            scope["path"] = new_path
            scope["raw_path"] = new_path.encode("utf-8")

        await self.app(scope, receive, send)

    def _normalize_path(self, path: str) -> str | None:
        """Rewrite paths to start at the first recognized API root segment."""
        return normalize_api_path(path, self.valid_roots)
