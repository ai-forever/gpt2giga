"""Anthropic router package."""

from fastapi import APIRouter

_router: APIRouter | None = None


def _build_router() -> APIRouter:
    router = APIRouter()

    from gpt2giga.api.anthropic.batches import router as batches_router
    from gpt2giga.api.anthropic.messages import router as messages_router

    router.include_router(messages_router)
    router.include_router(batches_router)
    return router


def __getattr__(name: str):
    if name != "router":
        raise AttributeError(name)

    global _router
    if _router is None:
        _router = _build_router()
    return _router


__all__ = ["router"]
