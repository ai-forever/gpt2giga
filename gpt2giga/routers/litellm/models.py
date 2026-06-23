from typing import Optional

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.openapi_tags import OPENAPI_TAG_LITELLM_MODEL_INFO
from gpt2giga.providers.fusion.model_discovery import (
    build_fusion_litellm_model_info,
    find_fusion_litellm_model_info,
    get_request_fusion_settings,
)

router = APIRouter(tags=[OPENAPI_TAG_LITELLM_MODEL_INFO])


def _extract_model_id(model_info: object) -> str:
    """Extract a model id from GigaChat or OpenAI-like model objects."""
    model_id = getattr(model_info, "id_", None) or getattr(model_info, "id", None)
    if model_id is None and hasattr(model_info, "model_dump"):
        model_data = model_info.model_dump(by_alias=True)
        if isinstance(model_data, dict):
            model_id = model_data.get("id") or model_data.get("id_")
    if model_id is None:
        raise AttributeError("Model object must expose `id_` or `id`.")
    return str(model_id)


def _model_info_entry(model_id: str) -> dict:
    return {
        "model_name": model_id,
        "litellm_params": {"model": model_id},
        "model_info": {"id": model_id},
    }


@router.get("/model/info")
@exceptions_handler
async def get_model_info(request: Request, model: Optional[str] = None):
    """Return LiteLLM-style model info."""
    fusion_settings = get_request_fusion_settings(request)
    if model:
        fusion_model_info = find_fusion_litellm_model_info(model, fusion_settings)
        if fusion_model_info is not None:
            return fusion_model_info

    giga_client = get_gigachat_client(request)
    request_options = extract_gigachat_request_options(
        request, exclude_query_params=("model",)
    )
    if model:
        async with gigachat_request_options(giga_client, request_options):
            response = await giga_client.aget_model(model=model)
        return _model_info_entry(_extract_model_id(response))
    async with gigachat_request_options(giga_client, request_options):
        response = await giga_client.aget_models()
    return {
        "data": [
            _model_info_entry(_extract_model_id(model_info))
            for model_info in response.data
        ]
        + build_fusion_litellm_model_info(fusion_settings)
    }
