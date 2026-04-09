"""Gemini-compatible router package."""

from fastapi import APIRouter

from gpt2giga.api.gemini.content import router as content_router
from gpt2giga.api.gemini.models import router as models_router

router = APIRouter(tags=["Gemini"])
router.include_router(content_router)
router.include_router(models_router)

__all__ = ["router"]
