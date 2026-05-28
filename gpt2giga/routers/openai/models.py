"""Model discovery endpoints."""

import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)

router = APIRouter(tags=["OpenAI"])


def _is_anthropic_models_request(request: Request) -> bool:
    user_agent = request.headers.get("user-agent", "")
    return (
        "anthropic-version" in request.headers
        or "anthropic-beta" in request.headers
        or user_agent.lower().startswith("anthropic/")
    )


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)
    if isinstance(model, dict):
        return dict(model)
    return {key: value for key, value in vars(model).items() if not key.startswith("_")}


def _model_id(model: dict[str, Any]) -> str:
    return str(model.get("id") or model.get("id_") or model.get("model") or "")


def _anthropic_created_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_anthropic_model(model: dict[str, Any]) -> dict[str, Any]:
    model_id = _model_id(model)
    return {
        "id": model_id,
        "created_at": _anthropic_created_at(),
        "display_name": str(model.get("display_name") or model_id),
        "type": "model",
    }


def _paginate_anthropic_models(
    models: list[dict[str, Any]],
    *,
    after_id: Optional[str],
    before_id: Optional[str],
    limit: Optional[int],
) -> tuple[list[dict[str, Any]], bool]:
    if after_id:
        for index, model in enumerate(models):
            if model["id"] == after_id:
                models = models[index + 1 :]
                break

    if before_id:
        for index, model in enumerate(models):
            if model["id"] == before_id:
                models = models[:index]
                break

    if limit is None:
        return models, False

    return models[:limit], len(models) > limit


def _query_limit(request: Request) -> Optional[int]:
    raw_limit = request.query_params.get("limit")
    if raw_limit is None:
        return None
    try:
        limit = int(raw_limit)
    except ValueError:
        return None
    return limit if limit > 0 else None


def _build_anthropic_model_list(
    models: list[dict[str, Any]],
    request: Request,
) -> dict[str, Any]:
    anthropic_models = [_build_anthropic_model(model) for model in models]
    page, has_more = _paginate_anthropic_models(
        anthropic_models,
        after_id=request.query_params.get("after_id"),
        before_id=request.query_params.get("before_id"),
        limit=_query_limit(request),
    )
    return {
        "data": page,
        "has_more": has_more,
        "first_id": page[0]["id"] if page else None,
        "last_id": page[-1]["id"] if page else None,
    }


@router.get("/models")
@exceptions_handler
async def show_available_models(request: Request):
    """List available GigaChat models in OpenAI-compatible form."""
    giga_client = get_gigachat_client(request)
    request_options = extract_gigachat_request_options(request)
    async with gigachat_request_options(giga_client, request_options):
        response = await giga_client.aget_models()
    models = [_dump_model(item) for item in response.data]
    if _is_anthropic_models_request(request):
        return _build_anthropic_model_list(models, request)

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
    request_options = extract_gigachat_request_options(request)
    async with gigachat_request_options(giga_client, request_options):
        response = await giga_client.aget_model(model=model)
    model_data = _dump_model(response)
    if _is_anthropic_models_request(request):
        return _build_anthropic_model(model_data)

    model_data["created"] = int(time.time())
    return OpenAIModel(**model_data)
