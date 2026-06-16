"""Gemini-compatible embedding endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.context import get_request_context, update_request_context
from gpt2giga.openapi_specs.gemini import gemini_embed_content_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_EMBEDDINGS
from gpt2giga.protocol.embeddings import (
    normalize_embedding_response,
    transform_embedding_body,
)
from gpt2giga.protocols.normalized import NormalizedEmbeddingRequest
from gpt2giga.sinks.observability.embeddings import emit_openai_embeddings_observability

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_EMBEDDINGS])


@router.post(
    "/models/{model}:embedContent",
    openapi_extra=gemini_embed_content_openapi_extra(batch=False),
)
@exceptions_handler
async def embed_content(model: str, request: Request):
    """Create one Gemini-compatible embedding."""
    data = await read_request_json(request)
    requested_model = model.removeprefix("models/")
    update_request_context(
        model_requested=requested_model,
        metadata={"protocol": "gemini", "api_format": "embed_content"},
    )
    text = _content_text(data.get("content"), param="content")
    result = await _embed_texts(request, data, requested_model, [text])
    return _openai_embedding_to_gemini(result, index=0)


@router.post(
    "/models/{model}:batchEmbedContents",
    openapi_extra=gemini_embed_content_openapi_extra(batch=True),
)
@exceptions_handler
async def batch_embed_contents(model: str, request: Request):
    """Create Gemini-compatible embeddings for multiple requests."""
    data = await read_request_json(request)
    requested_model = model.removeprefix("models/")
    update_request_context(
        model_requested=requested_model,
        metadata={"protocol": "gemini", "api_format": "batch_embed_contents"},
    )
    requests = _batch_requests(data)
    texts = [
        _content_text(item.get("content"), param=f"requests[{index}].content")
        for index, item in enumerate(requests)
    ]
    result = await _embed_texts(request, data, requested_model, texts)
    return {
        "embeddings": [
            _openai_embedding_to_gemini(result, index=index)["embedding"]
            for index in range(len(texts))
        ]
    }


async def _embed_texts(
    request: Request,
    original_data: dict[str, Any],
    requested_model: str,
    texts: list[str],
) -> dict[str, Any]:
    proxy_settings = request.app.state.config.proxy_settings
    transformed = await transform_embedding_body(
        {"model": requested_model, "input": texts},
        proxy_settings.embeddings,
        pass_model=proxy_settings.pass_model,
    )
    effective_model = transformed["model"]
    update_request_context(model_effective=effective_model)
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    request_options = extract_gigachat_request_options(request, original_data)
    async with model_limiter.limit(effective_model, provider="gemini"):
        async with gigachat_request_options(giga_client, request_options):
            response = await giga_client.aembeddings(
                texts=transformed["input"],
                model=effective_model,
            )
    result = normalize_embedding_response(response, model=effective_model)
    await emit_openai_embeddings_observability(
        request.app.state,
        _normalized_embedding_request(
            requested_model,
            original_data,
            transformed,
        ).to_json_dict(),
        transformed,
        result,
        context=get_request_context(),
    )
    return result


def _normalized_embedding_request(
    requested_model: str,
    original_data: dict[str, Any],
    transformed: dict[str, Any],
) -> NormalizedEmbeddingRequest:
    return NormalizedEmbeddingRequest(
        protocol="gemini",
        operation="embeddings",
        model=requested_model,
        input=transformed["input"],
        dimensions=original_data.get("outputDimensionality")
        or original_data.get("output_dimensionality"),
    )


def _openai_embedding_to_gemini(
    response: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    data = response.get("data")
    item = data[index] if isinstance(data, list) and index < len(data) else {}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    return {
        "embedding": {
            "values": item.get("embedding", []) if isinstance(item, dict) else []
        },
        "usageMetadata": {
            "promptTokenCount": usage.get("prompt_tokens"),
            "totalTokenCount": usage.get("total_tokens"),
        },
    }


def _batch_requests(data: dict[str, Any]) -> list[Mapping[str, Any]]:
    if "requests" not in data:
        raise _invalid_embedding_request(
            "`requests` is required for batchEmbedContents.",
            param="requests",
        )
    requests = data.get("requests")
    if not isinstance(requests, list):
        raise _invalid_embedding_request(
            "`requests` must be a non-empty list.",
            param="requests",
        )
    if not requests:
        raise _invalid_embedding_request(
            "`requests` must be a non-empty list.",
            param="requests",
        )
    normalized_requests: list[Mapping[str, Any]] = []
    for index, item in enumerate(requests):
        if not isinstance(item, Mapping):
            raise _invalid_embedding_request(
                "Each batchEmbedContents request entry must be an object.",
                param=f"requests[{index}]",
            )
        normalized_requests.append(item)
    return normalized_requests


def _content_text(value: Any, *, param: str) -> str:
    if value is None:
        raise _invalid_embedding_request(
            f"`{param}` is required.",
            param=param,
        )
    if isinstance(value, str):
        if not value:
            raise _invalid_embedding_request(
                f"`{param}` must contain non-empty text.",
                param=param,
            )
        return value
    if not isinstance(value, Mapping):
        raise _invalid_embedding_request(
            f"`{param}` must be a Gemini content object with text parts.",
            param=param,
        )
    parts = value.get("parts")
    if isinstance(parts, Mapping):
        parts = [parts]
    if not isinstance(parts, list):
        raise _invalid_embedding_request(
            f"`{param}.parts` must be a non-empty list of text parts.",
            param=f"{param}.parts",
        )
    if not parts:
        raise _invalid_embedding_request(
            f"`{param}.parts` must be a non-empty list of text parts.",
            param=f"{param}.parts",
        )

    texts: list[str] = []
    for index, part in enumerate(parts):
        part_param = f"{param}.parts[{index}]"
        if not isinstance(part, Mapping):
            raise _invalid_embedding_request(
                "Gemini embedding parts must be objects.",
                param=part_param,
            )
        if "text" not in part:
            raise _invalid_embedding_request(
                "Gemini embeddings only support text parts.",
                param=part_param,
            )
        text = part.get("text")
        if not isinstance(text, str) or not text:
            raise _invalid_embedding_request(
                "Gemini embedding text parts must be non-empty strings.",
                param=f"{part_param}.text",
            )
        texts.append(text)
    return "".join(texts)


def _invalid_embedding_request(message: str, *, param: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": param,
                "code": "invalid_request",
            }
        },
    )
