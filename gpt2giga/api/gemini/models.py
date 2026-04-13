"""Gemini model discovery routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from gpt2giga.api.gemini.request import normalize_model_name
from gpt2giga.api.gemini.response import gemini_exceptions_handler
from gpt2giga.api.tags import TAG_MODELS
from gpt2giga.features.models import get_models_service_from_state
from gpt2giga.providers.gemini import gemini_provider_adapters
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=[TAG_MODELS])


@router.get("/models")
@gemini_exceptions_handler
async def list_models(request: Request):
    """List available models in Gemini-compatible format."""
    models_service = get_models_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    return {
        "models": [
            gemini_provider_adapters.models.serialize_model(model)
            for model in await models_service.list_models(
                giga_client=giga_client,
                include_embeddings_model=True,
            )
        ]
    }


@router.get("/models/{model}")
@gemini_exceptions_handler
async def get_model(model: str, request: Request):
    """Return a single model in Gemini-compatible format."""
    models_service = get_models_service_from_state(request.app.state)
    normalized_model = normalize_model_name(model)
    giga_client = get_gigachat_client(request)
    descriptor = await models_service.get_model(
        normalized_model,
        giga_client=giga_client,
        allow_embeddings_model=True,
    )
    return gemini_provider_adapters.models.serialize_model(descriptor)
