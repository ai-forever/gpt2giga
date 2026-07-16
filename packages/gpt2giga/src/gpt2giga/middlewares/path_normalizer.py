from starlette.types import ASGIApp, Receive, Scope, Send


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
        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return None

        for index, segment in enumerate(segments):
            if segment not in self.valid_roots:
                continue
            normalized_segments = segments[index:]
            if self._has_outer_gateway_version_prefix(normalized_segments):
                normalized_segments.pop(1)

            while (
                len(normalized_segments) > 1
                and normalized_segments[0] in {"v1", "v2"}
                and normalized_segments[1] == normalized_segments[0]
            ):
                normalized_segments.pop(1)

            if index == 0 and normalized_segments == segments:
                return None
            return "/" + "/".join(normalized_segments)

        return None

    def _has_outer_gateway_version_prefix(self, segments: list[str]) -> bool:
        """Return whether Claude gateway v2 wraps an inner API version segment."""
        return (
            len(segments) > 2
            and segments[0] == "v2"
            and segments[1] in {"v1", "v2"}
            and segments[2] in self.valid_roots
        )
