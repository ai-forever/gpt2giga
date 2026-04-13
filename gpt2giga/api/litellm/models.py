from typing import Optional

from fastapi import APIRouter, Request

from gpt2giga.api.tags import PROVIDER_OPENAI, TAG_MODELS, provider_tag
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.features.models import get_models_service_from_state
from gpt2giga.features.models.contracts import ModelDescriptor
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=[provider_tag(TAG_MODELS, PROVIDER_OPENAI)])


def _model_info_entry(model: ModelDescriptor) -> dict[str, object]:
    """Build a LiteLLM-compatible model-info payload."""
    model_id = model["id"]
    return {
        "model_name": model_id,
        "litellm_params": {"model": model_id},
        "model_info": {"id": model_id},
    }


@router.get("/model/info")
@exceptions_handler
async def get_model_info(request: Request, model: Optional[str] = None):
    """Return LiteLLM-style model info."""
    models_service = get_models_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    if model:
        descriptor = await models_service.get_model(model, giga_client=giga_client)
        return _model_info_entry(descriptor)
    return {
        "data": [
            _model_info_entry(model_info)
            for model_info in await models_service.list_models(giga_client=giga_client)
        ]
    }
