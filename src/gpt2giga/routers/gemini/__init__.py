"""Gemini-compatible router aggregation."""

from fastapi import APIRouter

from gpt2giga.routers.gemini.embeddings import router as embeddings_router
from gpt2giga.routers.gemini.generate_content import router as generate_content_router
from gpt2giga.routers.gemini.models import router as models_router
from gpt2giga.routers.gemini.files import router as files_router
from gpt2giga.routers.gemini.batches import router as batches_router
from gpt2giga.routers.gemini.batches import operations_router as batch_operations_router

router = APIRouter()
router.include_router(models_router)
router.include_router(generate_content_router)
router.include_router(embeddings_router)
router.include_router(files_router)
router.include_router(batches_router)
router.include_router(batch_operations_router)

operations_router = APIRouter()
operations_router.include_router(generate_content_router)
operations_router.include_router(embeddings_router)
operations_router.include_router(batch_operations_router)

__all__ = ["operations_router", "router"]
