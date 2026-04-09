"""Model discovery endpoints."""

import time

from fastapi import APIRouter, Request
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.features.models import get_models_service_from_state
from gpt2giga.features.models.contracts import ModelDescriptor
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


def _serialize_openai_model(model: ModelDescriptor) -> OpenAIModel:
    """Build an OpenAI-compatible model object from an internal descriptor."""
    return OpenAIModel(
        id=model["id"],
        object=model["object"],
        owned_by=model["owned_by"],
        created=int(time.time()),
    )


@router.get("/models")
@exceptions_handler
async def show_available_models(request: Request):
    """List available GigaChat models in OpenAI-compatible form."""
    models_service = get_models_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    model_page = AsyncPage(
        data=[
            _serialize_openai_model(model)
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
    return _serialize_openai_model(descriptor)
