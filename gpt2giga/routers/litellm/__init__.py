"""LiteLLM-compatible router package."""

from fastapi import APIRouter

from gpt2giga.routers.litellm.models import router as models_router

router = APIRouter(tags=["LiteLLM"])
router.include_router(models_router)

__all__ = ["router"]


