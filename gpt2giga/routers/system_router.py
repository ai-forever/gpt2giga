from fastapi import APIRouter
from starlette.responses import Response

from gpt2giga.common.exceptions import exceptions_handler

system_router = APIRouter(tags=["System"])


@system_router.get("/health", response_class=Response)
@exceptions_handler
async def health() -> Response:
    """Health check."""
    return Response(status_code=200)


@system_router.get("/ping", response_class=Response)
@system_router.post("/ping", response_class=Response)
@exceptions_handler
async def ping() -> Response:
    return await health()
