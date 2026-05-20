from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class PathNormalizationMiddleware(BaseHTTPMiddleware):
    """
    Redirects any path that contains a known valid segment
    (like /v1/, /models/ etc. ) after some extra unnecessary prefixes.
    """

    def __init__(self, app, valid_roots=None):
        super().__init__(app)
        # Valid entrypoints
        self.valid_roots = valid_roots or [
            "v1",
            "chat",
            "models",
            "embeddings",
            "messages",
            "responses",
        ]

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path
        new_path = self._normalize_path(path)
        if new_path is not None:
            # IMPORTANT:
            # Do not redirect (307) here: some clients may re-issue the request
            # without the original body, which leads to JSONDecodeError in
            # downstream handlers. Instead, rewrite the ASGI scope path in-place.
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")

        return await call_next(request)

    def _normalize_path(self, path: str) -> str | None:
        """Rewrite paths to start at the first recognized API root segment."""
        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return None

        for index, segment in enumerate(segments):
            if segment not in self.valid_roots:
                continue
            normalized_segments = segments[index:]
            while (
                len(normalized_segments) > 1
                and normalized_segments[0] == "v1"
                and normalized_segments[1] == "v1"
            ):
                normalized_segments.pop(1)

            if index == 0 and normalized_segments == segments:
                return None
            return "/" + "/".join(normalized_segments)

        return None
