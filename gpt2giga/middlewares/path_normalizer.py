import re
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse


class PathNormalizationMiddleware(BaseHTTPMiddleware):
    """
    Redirects any path that contains a known valid segment
    (like /v1/, /models/ etc. ) after some extra unnecessary prefixes.
    """

    def __init__(self, app, valid_roots=None):
        super().__init__(app)
        # Valid entrypoints
        self.valid_roots = valid_roots or ["v1", "chat", "models", "embeddings"]
        pattern = r".*/(" + "|".join(map(re.escape, self.valid_roots)) + r")(/.*|$)"
        self._pattern = re.compile(pattern)

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        match = self._pattern.match(path)

        if match and not path.startswith(f"/{match.group(1)}"):
            new_path = f"/{match.group(1)}{match.group(2)}"
            query = request.url.query
            if query:
                new_path += f"?{query}"
            return RedirectResponse(url=new_path)

        return await call_next(request)
