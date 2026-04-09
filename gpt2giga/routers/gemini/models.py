"""Gemini model discovery routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.protocol.gemini import (
    build_gemini_model,
    gemini_exceptions_handler,
    normalize_model_name,
)

router = APIRouter(tags=["Gemini"])


def _extract_model_id(model_obj: Any) -> str:
    """Extract a plain model id from a GigaChat model object."""
    if hasattr(model_obj, "model_dump"):
        payload = model_obj.model_dump(by_alias=True)
        for key in ("id", "id_", "name"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return normalize_model_name(value)
    for attr in ("id_", "id", "name"):
        value = getattr(model_obj, attr, None)
        if isinstance(value, str) and value:
            return normalize_model_name(value)
    return "unknown"


def _serialize_generation_model(model_id: str) -> dict[str, Any]:
    """Build a Gemini-compatible descriptor for a chat-capable model."""
    return build_gemini_model(
        model_id,
        supported_generation_methods=["generateContent", "countTokens"],
        input_token_limit=32768,
        output_token_limit=8192,
        description="GigaChat model exposed through gpt2giga Gemini compatibility.",
        thinking=True,
    )


def _serialize_embeddings_model(model_id: str) -> dict[str, Any]:
    """Build a Gemini-compatible descriptor for the proxy embeddings model."""
    return build_gemini_model(
        model_id,
        supported_generation_methods=["embedContent"],
        input_token_limit=8192,
        output_token_limit=1,
        description="Proxy-configured embeddings model exposed through Gemini compatibility.",
        thinking=False,
    )


@router.get("/models")
@gemini_exceptions_handler
async def list_models(request: Request):
    """List available models in Gemini-compatible format."""
    giga_client = get_gigachat_client(request)
    response = await giga_client.aget_models()
    models = [
        _serialize_generation_model(_extract_model_id(item)) for item in response.data
    ]

    embeddings_model = normalize_model_name(
        request.app.state.config.proxy_settings.embeddings
    )
    if embeddings_model and not any(
        model["name"] == f"models/{embeddings_model}" for model in models
    ):
        models.append(_serialize_embeddings_model(embeddings_model))

    return {"models": models}


@router.get("/models/{model}")
@gemini_exceptions_handler
async def get_model(model: str, request: Request):
    """Return a single model in Gemini-compatible format."""
    normalized_model = normalize_model_name(model)
    embeddings_model = normalize_model_name(
        request.app.state.config.proxy_settings.embeddings
    )
    if normalized_model == embeddings_model:
        return _serialize_embeddings_model(normalized_model)

    giga_client = get_gigachat_client(request)
    response = await giga_client.aget_model(model=normalized_model)
    return _serialize_generation_model(_extract_model_id(response))
