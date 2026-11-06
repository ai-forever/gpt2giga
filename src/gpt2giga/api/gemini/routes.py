"""Gemini-compatible API routes."""

from fastapi import APIRouter

from gpt2giga.routers.gemini import (
    operations_router as gemini_operations_router,
)
from gpt2giga.routers.gemini import router as gemini_router

# Protocol-specific Files routes live under the Gemini API prefixes.

router = APIRouter()
router.include_router(gemini_router)

operations_router = APIRouter()
operations_router.include_router(gemini_operations_router)

__all__ = ["operations_router", "router"]
