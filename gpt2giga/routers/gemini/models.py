"""Gemini-compatible model discovery endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.openapi_specs.gemini import gemini_models_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_MODELS

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_MODELS])


@router.get("/models", openapi_extra=gemini_models_openapi_extra(list_models=True))
@exceptions_handler
async def list_models(request: Request):
    """List models in Gemini-compatible form."""
    giga_client = get_gigachat_client(request)
    request_options = extract_gigachat_request_options(request)
    async with gigachat_request_options(giga_client, request_options):
        response = await giga_client.aget_models()
    return {
        "models": [_model_to_gemini(_dump_model(item)) for item in response.data],
        "nextPageToken": "",
    }


@router.get(
    "/models/{model}",
    openapi_extra=gemini_models_openapi_extra(list_models=False),
)
@exceptions_handler
async def get_model(model: str, request: Request):
    """Return one model in Gemini-compatible form."""
    requested_model = model.removeprefix("models/")
    giga_client = get_gigachat_client(request)
    request_options = extract_gigachat_request_options(request)
    async with gigachat_request_options(giga_client, request_options):
        response = await giga_client.aget_model(model=requested_model)
    return _model_to_gemini(_dump_model(response))


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)
    if isinstance(model, dict):
        return dict(model)
    return {key: value for key, value in vars(model).items() if not key.startswith("_")}


def _model_to_gemini(model: dict[str, Any]) -> dict[str, Any]:
    model_id = str(model.get("id") or model.get("id_") or model.get("model") or "")
    display_name = str(model.get("display_name") or model.get("owned_by") or model_id)
    return {
        "name": f"models/{model_id}",
        "baseModelId": model_id,
        "version": str(model.get("version") or ""),
        "displayName": display_name,
        "description": "GigaChat model exposed through the Gemini-compatible API.",
        "inputTokenLimit": int(model.get("input_token_limit") or 0),
        "outputTokenLimit": int(model.get("output_token_limit") or 0),
        "supportedGenerationMethods": [
            "generateContent",
            "streamGenerateContent",
            "countTokens",
        ],
    }
