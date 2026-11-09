"""Gemini-compatible model discovery endpoints."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from gpt2giga.app_state import (
    get_gigachat_client,
    get_gigachat_model_catalog,
    get_gigachat_model_catalog_profile_id,
    record_gigachat_model_catalog_snapshot,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.capabilities import (
    CapabilityKey,
    CapabilityState,
    resolve_gigachat_model_layer,
)
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.models.catalog import ModelDescriptor, ModelNotFoundError
from gpt2giga.openapi_specs.gemini import gemini_models_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_MODELS
from gpt2giga.providers.profiles.static_catalog import static_registry_model_payloads

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_MODELS])

_EMBEDDING_METHODS = [
    "embedContent",
    "batchEmbedContents",
]
_MODEL_PROJECTION_QUERY_PARAMS = (
    "page_size",
    "pageSize",
    "page_token",
    "pageToken",
    "refresh",
)


@router.get("/models", openapi_extra=gemini_models_openapi_extra(list_models=True))
@exceptions_handler
async def list_models(request: Request):
    """List models in Gemini-compatible form."""
    registry = getattr(request.app.state, "provider_registry", None)
    models = static_registry_model_payloads(registry) if registry is not None else None
    if models is None:
        giga_client = get_gigachat_client(request)
        catalog = get_gigachat_model_catalog(request)
        request_options = extract_gigachat_request_options(
            request,
            exclude_query_params=_MODEL_PROJECTION_QUERY_PARAMS,
        )
        async with gigachat_request_options(
            giga_client, request_options, include_body=False
        ) as request_client:
            snapshot = await catalog.list_models(
                request_client,
                provider_profile_id=get_gigachat_model_catalog_profile_id(request),
                refresh=_catalog_refresh_requested(request),
            )
        record_gigachat_model_catalog_snapshot(request, snapshot)
        models = [catalog_model_payload(item) for item in snapshot.models]
    return build_gemini_model_list(models, request=request)


@router.get(
    "/models/{model}",
    openapi_extra=gemini_models_openapi_extra(list_models=False),
)
@exceptions_handler
async def get_model(model: str, request: Request):
    """Return one model in Gemini-compatible form."""
    requested_model = model.removeprefix("models/")
    registry = getattr(request.app.state, "provider_registry", None)
    static_models = (
        static_registry_model_payloads(registry) if registry is not None else None
    )
    if static_models is not None:
        try:
            model_payload = next(
                item for item in static_models if item["id"] == requested_model
            )
        except StopIteration as exc:
            raise HTTPException(status_code=404, detail="Model not found") from exc
    else:
        giga_client = get_gigachat_client(request)
        catalog = get_gigachat_model_catalog(request)
        request_options = extract_gigachat_request_options(
            request,
            exclude_query_params=_MODEL_PROJECTION_QUERY_PARAMS,
        )
        async with gigachat_request_options(
            giga_client, request_options, include_body=False
        ) as request_client:
            try:
                descriptor = await catalog.get_model(
                    requested_model,
                    request_client,
                    provider_profile_id=get_gigachat_model_catalog_profile_id(request),
                    refresh=_catalog_refresh_requested(request),
                )
            except ModelNotFoundError as exc:
                raise HTTPException(status_code=404, detail="Model not found") from exc
        model_payload = catalog_model_payload(descriptor)
    return build_gemini_model(model_payload)


def dump_model_payload(model: Any) -> dict[str, Any]:
    """Return a plain mapping for a GigaChat model object."""
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True)
    if isinstance(model, dict):
        return dict(model)
    return {key: value for key, value in vars(model).items() if not key.startswith("_")}


def catalog_model_payload(model: ModelDescriptor) -> dict[str, Any]:
    """Rebuild a provider-shaped payload from one catalog descriptor."""
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
    return payload


def _catalog_refresh_requested(request: Request) -> bool:
    return request.query_params.get("refresh", "").casefold() in {"1", "true", "yes"}


def build_gemini_model_list(
    models: list[dict[str, Any]], *, request: Request | None = None
) -> dict[str, Any]:
    """Build a Gemini-compatible model list payload."""
    projected = [build_gemini_model(model) for model in models]
    if request is None:
        return {"models": projected, "nextPageToken": ""}
    query = request.query_params
    try:
        page_size = int(query.get("pageSize", query.get("page_size", "50")))
    except ValueError as exc:
        raise HTTPException(400, "pageSize must be a positive integer") from exc
    if not 1 <= page_size <= 1000:
        raise HTTPException(400, "pageSize must be between 1 and 1000")
    # Bind the cursor to a stable ordering and the current visible inventory.
    projected.sort(key=lambda item: item["name"])
    revision = hashlib.sha256(
        json.dumps(projected, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    offset = 0
    token = query.get("pageToken", query.get("page_token", ""))
    if token:
        try:
            if len(token) > 1024:
                raise ValueError
            cursor = json.loads(base64.b64decode(token, altchars=b"-_", validate=True))
            offset = cursor["offset"]
            if (
                type(offset) is not int
                or not 0 < offset < len(projected)
                or cursor["revision"] != revision
            ):
                raise ValueError
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, "Invalid or stale pageToken") from exc
    end = offset + page_size
    next_token = ""
    if end < len(projected):
        next_token = base64.urlsafe_b64encode(
            json.dumps({"offset": end, "revision": revision}).encode()
        ).decode()
    return {
        "models": projected[offset:end],
        "nextPageToken": next_token,
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
    explicit = model.get(
        "supportedGenerationMethods", model.get("supported_generation_methods")
    )
    if isinstance(explicit, list) and all(isinstance(item, str) for item in explicit):
        return list(explicit)

    model_type = str(model.get("type") or "").casefold()
    declared = model.get("capabilities")
    labels = (
        {item for item in declared if isinstance(item, str)}
        if isinstance(declared, list)
        else set()
    )
    if (
        model_type in {"embedder", "embedding", "embeddings"}
        or labels & {"embedder", "embedding", "embeddings"}
        or model_id in {"Embeddings", "EmbeddingsGigaR"}
    ):
        return list(_EMBEDDING_METHODS)
    layer = resolve_gigachat_model_layer(model_id, "v2")
    text = (
        layer.capabilities[CapabilityKey.TEXT_INPUT].state is CapabilityState.SUPPORTED
    )
    streaming = (
        layer.capabilities[CapabilityKey.STREAMING].state is CapabilityState.SUPPORTED
    )
    # Exact legacy aliases retain their existing text contract. Names of future
    # models, owners and free-text descriptions are never capability evidence.
    if (
        model_type in {"chat", "text", "generation", "completion", "llm"}
        or labels & {"chat", "generation", "text"}
        or model_id in {"GigaChat", "GigaChat-Pro", "GigaChat-Plus", "GigaChat-Max"}
    ):
        text = streaming = True
    if isinstance(declared, dict):
        text = _declared_support(declared.get("text_input"), text)
        streaming = _declared_support(declared.get("streaming"), streaming)
    methods = []
    if text:
        methods.append("generateContent")
        if streaming:
            methods.append("streamGenerateContent")
        methods.append("countTokens")
    return methods


def _declared_support(value: Any, default: bool) -> bool:
    if isinstance(value, dict):
        value = value.get("state")
    if value is True or value == "supported":
        return True
    if value is False or value in ("unsupported", "unknown"):
        return False
    return default
