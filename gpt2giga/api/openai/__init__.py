"""OpenAI-compatible router package."""

from fastapi import APIRouter

_router: APIRouter | None = None


def _build_router() -> APIRouter:
    router = APIRouter()

    from gpt2giga.api.openai.batches import router as batches_router
    from gpt2giga.api.openai.chat import router as chat_router
    from gpt2giga.api.openai.embeddings import router as embeddings_router
    from gpt2giga.api.openai.files import router as files_router
    from gpt2giga.api.openai.models import router as models_router
    from gpt2giga.api.openai.responses import router as responses_router

    router.include_router(models_router)
    router.include_router(chat_router)
    router.include_router(embeddings_router)
    router.include_router(responses_router)
    router.include_router(files_router)
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
