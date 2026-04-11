"""Model discovery endpoints."""

from fastapi import APIRouter, Request
from openai.pagination import AsyncPage

from gpt2giga.core.errors import exceptions_handler
from gpt2giga.features.models import get_models_service_from_state
from gpt2giga.providers.openai import openai_provider_adapters
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


@router.get("/models")
@exceptions_handler
async def show_available_models(request: Request):
    """List available GigaChat models in OpenAI-compatible form."""
    models_service = get_models_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    model_page = AsyncPage(
        data=[
            openai_provider_adapters.models.serialize_model(model)
            for model in await models_service.list_models(giga_client=giga_client)
        ],
        object="list",
    )
    return model_page


@router.get("/models/{model}")
@exceptions_handler
async def get_model(model: str, request: Request):
    """Return a single model."""
    models_service = get_models_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    descriptor = await models_service.get_model(model, giga_client=giga_client)
    return openai_provider_adapters.models.serialize_model(descriptor)
