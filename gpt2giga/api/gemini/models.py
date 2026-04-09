"""Gemini model discovery routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from gpt2giga.api.gemini.request import normalize_model_name
from gpt2giga.api.gemini.response import build_gemini_model, gemini_exceptions_handler
from gpt2giga.features.models import get_models_service_from_state
from gpt2giga.features.models.contracts import ModelDescriptor
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["Gemini"])


def _serialize_generation_model(model_id: str) -> dict[str, object]:
    """Build a Gemini-compatible descriptor for a chat-capable model."""
    return build_gemini_model(
        model_id,
        supported_generation_methods=["generateContent", "countTokens"],
        input_token_limit=32768,
        output_token_limit=8192,
        description="GigaChat model exposed through gpt2giga Gemini compatibility.",
        thinking=True,
    )


def _serialize_embeddings_model(model_id: str) -> dict[str, object]:
    """Build a Gemini-compatible descriptor for the proxy embeddings model."""
    return build_gemini_model(
        model_id,
        supported_generation_methods=["embedContent"],
        input_token_limit=8192,
        output_token_limit=1,
        description="Proxy-configured embeddings model exposed through Gemini compatibility.",
        thinking=False,
    )


def _serialize_gemini_model(model: ModelDescriptor) -> dict[str, object]:
    """Build a Gemini-compatible descriptor from an internal model descriptor."""
    model_id = normalize_model_name(model["id"])
    if model["kind"] == "embeddings":
        return _serialize_embeddings_model(model_id)
    return _serialize_generation_model(model_id)


@router.get("/models")
@gemini_exceptions_handler
async def list_models(request: Request):
    """List available models in Gemini-compatible format."""
    models_service = get_models_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    return {
        "models": [
            _serialize_gemini_model(model)
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
    return _serialize_gemini_model(descriptor)
