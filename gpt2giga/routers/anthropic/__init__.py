"""Anthropic router package."""

from fastapi import APIRouter

from gpt2giga.routers.anthropic.messages import router as messages_router

# TODO: enable with next gigachat lib release.
# from gpt2giga.routers.anthropic.batches import router as batches_router

router = APIRouter(tags=["Anthropic"])
router.include_router(messages_router)
# TODO: enable with next gigachat lib release.
# router.include_router(batches_router)

__all__ = ["router"]
