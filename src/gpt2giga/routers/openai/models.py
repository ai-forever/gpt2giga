"""Model discovery endpoints."""

import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from openai.pagination import AsyncPage
from openai.types import Model as OpenAIModel

from gpt2giga.app_state import (
    get_gigachat_client,
    get_gigachat_model_catalog,
    get_gigachat_model_catalog_profile_id,
    record_gigachat_model_catalog_snapshot,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.models.catalog import ModelDescriptor, ModelNotFoundError
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_MODELS
from gpt2giga.providers.profiles.static_catalog import static_registry_model_payloads
from gpt2giga.routers.gemini.models import (
    build_gemini_model,
    build_gemini_model_list,
)

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_MODELS])

_MODEL_PROJECTION_QUERY_PARAMS = (
    "after_id",
    "before_id",
    "limit",
    "page_size",
    "pageSize",
    "page_token",
    "pageToken",
    "refresh",
)


def _is_anthropic_models_request(request: Request) -> bool:
    user_agent = request.headers.get("user-agent", "")
    return (
        "anthropic-version" in request.headers
        or "anthropic-beta" in request.headers
        or user_agent.lower().startswith("anthropic/")
    )


def _is_gemini_models_request(request: Request) -> bool:
    user_agent = request.headers.get("user-agent", "").lower()
    return (
        "x-goog-api-client" in request.headers
        or "x-goog-api-key" in request.headers
        or "x-goog-user-project" in request.headers
        or request.query_params.get("key") is not None
        or "google-generative-ai" in user_agent
        or user_agent.startswith(("google-genai", "genai/"))
    )


def _catalog_model_payload(model: ModelDescriptor) -> dict[str, Any]:
    payload = dict(model.provider_metadata)
    payload.update(
        {
            "id": model.id,
            "object": payload.get("object") or "model",
            "owned_by": model.owned_by or model.provider_kind,
        }
    )
    if model.model_type is not None:
        payload["type"] = model.model_type
    if not model.available:
        payload["available"] = False
    if model.deprecated:
        payload["deprecated"] = True
    return payload


def _catalog_refresh_requested(request: Request) -> bool:
    return request.query_params.get("refresh", "").casefold() in {"1", "true", "yes"}


def _model_id(model: dict[str, Any]) -> str:
    return str(model.get("id") or model.get("id_") or model.get("model") or "")


def _add_model_type_metadata(model: dict[str, Any]) -> None:
    """Expose the upstream model kind after SDK normalization drops it."""
    raw_metadata = model.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    model_type = model.get("type")
    if not isinstance(model_type, str) or not model_type:
        model_type = (
            "embedder" if "embedding" in _model_id(model).casefold() else "chat"
        )
    metadata["type"] = model_type
    model["metadata"] = metadata


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
    registry = getattr(request.app.state, "provider_registry", None)
    models = static_registry_model_payloads(registry) if registry is not None else None
    object_name = "list"
    if models is None:
        giga_client = get_gigachat_client(request)
        catalog = get_gigachat_model_catalog(request)
        request_options = extract_gigachat_request_options(
            request,
            exclude_query_params=_MODEL_PROJECTION_QUERY_PARAMS,
        )
        async with gigachat_request_options(giga_client, request_options):
            snapshot = await catalog.list_models(
                giga_client,
                provider_profile_id=get_gigachat_model_catalog_profile_id(request),
                refresh=_catalog_refresh_requested(request),
            )
        record_gigachat_model_catalog_snapshot(request, snapshot)
        models = [_catalog_model_payload(item) for item in snapshot.models]
        object_name = str(snapshot.provider_metadata.get("object") or "list")
    if _is_anthropic_models_request(request):
        return _build_anthropic_model_list(models, request)
    if _is_gemini_models_request(request):
        return build_gemini_model_list(models)

    current_timestamp = int(time.time())
    for model in models:
        _add_model_type_metadata(model)
        model["created"] = current_timestamp
    model_page = AsyncPage(
        data=[OpenAIModel(**model) for model in models],
        object=object_name,
    )
    return model_page


@router.get("/models/{model}")
@exceptions_handler
async def get_model(model: str, request: Request):
    """Return a single model."""
    registry = getattr(request.app.state, "provider_registry", None)
    static_models = (
        static_registry_model_payloads(registry) if registry is not None else None
    )
    if static_models is not None:
        try:
            model_data = next(item for item in static_models if item["id"] == model)
        except StopIteration as exc:
            raise HTTPException(status_code=404, detail="Model not found") from exc
    else:
        giga_client = get_gigachat_client(request)
        catalog = get_gigachat_model_catalog(request)
        request_options = extract_gigachat_request_options(
            request,
            exclude_query_params=_MODEL_PROJECTION_QUERY_PARAMS,
        )
        async with gigachat_request_options(giga_client, request_options):
            try:
                descriptor = await catalog.get_model(
                    model,
                    giga_client,
                    provider_profile_id=get_gigachat_model_catalog_profile_id(request),
                    refresh=_catalog_refresh_requested(request),
                )
            except ModelNotFoundError as exc:
                raise HTTPException(status_code=404, detail="Model not found") from exc
        model_data = _catalog_model_payload(descriptor)
    if _is_anthropic_models_request(request):
        return _build_anthropic_model(model_data)
    if _is_gemini_models_request(request):
        return build_gemini_model(model_data)

    _add_model_type_metadata(model_data)
    model_data["created"] = int(time.time())
    return OpenAIModel(**model_data)
