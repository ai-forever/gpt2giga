"""OpenAI-compatible API router package."""

from fastapi import APIRouter

from gpt2giga.routers.api.batches import router as batches_router
from gpt2giga.routers.api.chat import router as chat_router
from gpt2giga.routers.api.files import router as files_router
from gpt2giga.routers.api.models import router as models_router

router = APIRouter(tags=["API"])
router.include_router(models_router)
router.include_router(chat_router)
router.include_router(files_router)
router.include_router(batches_router)

__all__ = ["router"]
