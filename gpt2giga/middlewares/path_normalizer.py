import re
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
        pattern = r".*/(" + "|".join(map(re.escape, self.valid_roots)) + r")(/.*|$)"
        self._pattern = re.compile(pattern)

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        match = self._pattern.match(path)

        if match and not path.startswith(f"/{match.group(1)}"):
            new_path = f"/{match.group(1)}{match.group(2)}"
            # IMPORTANT:
            # Do not redirect (307) here: some clients may re-issue the request
            # without the original body, which leads to JSONDecodeError in
            # downstream handlers. Instead, rewrite the ASGI scope path in-place.
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")

        return await call_next(request)
