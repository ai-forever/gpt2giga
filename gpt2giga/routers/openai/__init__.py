"""OpenAI-compatible router package."""

from fastapi import APIRouter

from gpt2giga.routers.openai.batches import router as batches_router
from gpt2giga.routers.openai.chat_completions import (
    router as chat_completions_router,
)
from gpt2giga.routers.openai.embeddings import router as embeddings_router
from gpt2giga.routers.openai.files import router as files_router
from gpt2giga.routers.openai.models import router as models_router
from gpt2giga.routers.openai.responses import router as responses_router

router = APIRouter(tags=["OpenAI"])
router.include_router(models_router)
router.include_router(chat_completions_router)
router.include_router(embeddings_router)
router.include_router(responses_router)
router.include_router(files_router)
router.include_router(batches_router)

__all__ = ["router"]
