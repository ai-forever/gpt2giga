"""Anthropic router package."""

from fastapi import APIRouter

from gpt2giga.api.anthropic.batches import router as batches_router
from gpt2giga.api.anthropic.messages import router as messages_router

router = APIRouter(tags=["Anthropic"])
router.include_router(messages_router)
router.include_router(batches_router)

__all__ = ["router"]
