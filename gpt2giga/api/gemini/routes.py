"""Gemini-compatible API routes."""

from fastapi import APIRouter

from gpt2giga.routers.gemini import router as gemini_router

# Files and Batches are implemented in ``gpt2giga.routers.gemini`` but are
# intentionally not included there yet.

router = APIRouter()
router.include_router(gemini_router)

__all__ = ["router"]
