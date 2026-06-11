"""Gemini-compatible router aggregation."""

from fastapi import APIRouter

from gpt2giga.routers.gemini.embeddings import router as embeddings_router
from gpt2giga.routers.gemini.generate_content import router as generate_content_router
from gpt2giga.routers.gemini.models import router as models_router

# Prepared but intentionally not mounted until file/batch execution semantics are
# validated end to end against the upstream backend.
# from gpt2giga.routers.gemini.batches import router as batches_router
# from gpt2giga.routers.gemini.files import router as files_router

router = APIRouter()
router.include_router(models_router)
router.include_router(generate_content_router)
router.include_router(embeddings_router)
# Keep disabled as a pair: Gemini batch jobs need File API inputs/results.
# router.include_router(files_router)
# router.include_router(batches_router)

operations_router = APIRouter()
operations_router.include_router(generate_content_router)
operations_router.include_router(embeddings_router)

__all__ = ["operations_router", "router"]
