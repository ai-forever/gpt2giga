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

_GENERATION_METHODS = [
    "generateContent",
    "streamGenerateContent",
    "countTokens",
]
_EMBEDDING_METHODS = [
    "embedContent",
    "batchEmbedContents",
]
_CONSERVATIVE_METHODS = ["countTokens"]


@router.get("/models", openapi_extra=gemini_models_openapi_extra(list_models=True))
@exceptions_handler
async def list_models(request: Request):
    """List models in Gemini-compatible form."""
    giga_client = get_gigachat_client(request)
    request_options = extract_gigachat_request_options(request)
    async with gigachat_request_options(giga_client, request_options):
        response = await giga_client.aget_models()
    return build_gemini_model_list([dump_model_payload(item) for item in response.data])


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
    return build_gemini_model(dump_model_payload(response))


def dump_model_payload(model: Any) -> dict[str, Any]:
    """Return a plain mapping for a GigaChat model object."""
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)
    if isinstance(model, dict):
        return dict(model)
    return {key: value for key, value in vars(model).items() if not key.startswith("_")}


def build_gemini_model_list(models: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a Gemini-compatible model list payload."""
    return {
        "models": [build_gemini_model(model) for model in models],
        "nextPageToken": "",
    }


def build_gemini_model(model: dict[str, Any]) -> dict[str, Any]:
    """Build one Gemini-compatible model payload."""
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
        "supportedGenerationMethods": _supported_generation_methods(model, model_id),
    }


def _supported_generation_methods(
    model: dict[str, Any],
    model_id: str,
) -> list[str]:
    explicit = model.get("supportedGenerationMethods") or model.get(
        "supported_generation_methods"
    )
    if isinstance(explicit, list) and all(isinstance(item, str) for item in explicit):
        return list(explicit)

    capability_text = _capability_text(model, model_id)
    if _is_embedding_model(capability_text):
        return list(_EMBEDDING_METHODS)
    if _is_generation_model(capability_text):
        return list(_GENERATION_METHODS)
    return list(_CONSERVATIVE_METHODS)


def _capability_text(model: dict[str, Any], model_id: str) -> str:
    values: list[str] = [model_id]
    for key in (
        "type",
        "object",
        "display_name",
        "description",
        "owned_by",
        "capabilities",
        "supported_methods",
    ):
        value = model.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    return " ".join(values).lower()


def _is_embedding_model(capability_text: str) -> bool:
    return any(
        marker in capability_text for marker in ("embedding", "embeddings", "embed")
    )


def _is_generation_model(capability_text: str) -> bool:
    return any(
        marker in capability_text
        for marker in (
            "gigachat",
            "chat",
            "completion",
            "generation",
            "gpt",
            "llm",
        )
    )
