"""Anthropic router package."""

from fastapi import APIRouter

from gpt2giga.routers.anthropic.messages import router as messages_router

# Keep Anthropic Message Batches unmounted until the GigaChat SDK exposes batch methods.
# from gpt2giga.routers.anthropic.batches import router as batches_router

router = APIRouter(tags=["Anthropic"])
router.include_router(messages_router)
# Keep Anthropic Message Batches unmounted until the GigaChat SDK exposes batch methods.
# router.include_router(batches_router)

__all__ = ["router"]
