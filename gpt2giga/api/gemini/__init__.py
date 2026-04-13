"""Gemini-compatible router package."""

from fastapi import APIRouter

_router: APIRouter | None = None


def _build_router() -> APIRouter:
    router = APIRouter()

    from gpt2giga.api.gemini.batches import router as batches_router
    from gpt2giga.api.gemini.content import router as content_router
    from gpt2giga.api.gemini.files import router as files_router
    from gpt2giga.api.gemini.models import router as models_router

    router.include_router(batches_router)
    router.include_router(content_router)
    router.include_router(files_router)
    router.include_router(models_router)
    return router


def __getattr__(name: str):
    if name != "router":
        raise AttributeError(name)

    global _router
    if _router is None:
        _router = _build_router()
    return _router


__all__ = ["router"]
