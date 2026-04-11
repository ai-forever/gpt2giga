"""LiteLLM-compatible router package."""

from fastapi import APIRouter

_router: APIRouter | None = None


def _build_router() -> APIRouter:
    router = APIRouter(tags=["LiteLLM"])

    from gpt2giga.api.litellm.models import router as models_router

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
