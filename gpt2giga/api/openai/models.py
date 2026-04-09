"""Model discovery endpoints."""

import time

from fastapi import APIRouter, Request
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


@router.get("/models")
@exceptions_handler
async def show_available_models(request: Request):
    """List available GigaChat models in OpenAI-compatible form."""
    giga_client = get_gigachat_client(request)
    response = await giga_client.aget_models()
    models = [item.model_dump(by_alias=True) for item in response.data]
    current_timestamp = int(time.time())
    for model in models:
        model["created"] = current_timestamp
    model_page = AsyncPage(
        data=[OpenAIModel(**model) for model in models],
        object=response.object_,
    )
    return model_page


@router.get("/models/{model}")
@exceptions_handler
async def get_model(model: str, request: Request):
    """Return a single model."""
    giga_client = get_gigachat_client(request)
    response = await giga_client.aget_model(model=model)
    model_data = response.model_dump(by_alias=True)
    model_data["created"] = int(time.time())
    return OpenAIModel(**model_data)
