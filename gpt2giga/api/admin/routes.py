"""Protected debug translation endpoints."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)
from gpt2giga.protocols.normalized import NormalizedChatRequest
from gpt2giga.protocols.openai import normalized_chat_response_to_openai
from gpt2giga.providers.gigachat.adapter import (
    gigachat_response_to_normalized,
    normalized_chat_to_openai_payload,
)


def verify_debug_admin_key(request: Request) -> None:
    """Require the configured admin key for debug translation routes."""
    settings = getattr(
        getattr(request.app.state, "config", None), "proxy_settings", None
    )
    expected = getattr(settings, "admin_api_key", None)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key is required",
        )

    supplied = _extract_admin_key(request)
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key",
        )


router = APIRouter(
    prefix="/_debug/translate",
    tags=["Debug"],
    dependencies=[Depends(verify_debug_admin_key)],
)


@router.post("/openai-to-normalized")
@exceptions_handler
async def openai_to_normalized(request: Request):
    """Translate an OpenAI Chat Completions request to normalized form."""
    payload = await _read_json_object(request)
    normalized = await request.app.state.openai_protocol_adapter.to_normalized(
        payload,
        context=None,
    )
    return {
        "source": "openai",
        "target": "normalized",
        "normalized": normalized.to_json_dict(),
    }


@router.post("/anthropic-to-normalized")
@exceptions_handler
async def anthropic_to_normalized(request: Request):
    """Translate an Anthropic Messages request to normalized form."""
    payload = await _read_json_object(request)
    logger = getattr(request.app.state, "logger", None)
    openai_payload = _build_openai_data_from_anthropic_request(payload, logger)
    normalized = await request.app.state.openai_protocol_adapter.to_normalized(
        openai_payload,
        context=None,
    )
    return {
        "source": "anthropic",
        "target": "normalized",
        "intermediate_openai": openai_payload,
        "normalized": normalized.to_json_dict(),
    }


@router.post("/normalized-to-gigachat")
@exceptions_handler
async def normalized_to_gigachat(request: Request):
    """Translate a normalized chat request to current GigaChat payload form."""
    payload = await _read_json_object(request)
    normalized_payload = payload.get("normalized", payload)
    normalized = NormalizedChatRequest.model_validate(normalized_payload)
    openai_payload = normalized_chat_to_openai_payload(normalized)
    state = request.app.state
    mode = getattr(state.config.proxy_settings, "gigachat_api_mode", "v1")
    giga_client = getattr(state, "gigachat_client", None)
    if mode == "v2":
        gigachat_payload = await state.request_transformer.prepare_chat_completion_v2(
            dict(openai_payload),
            giga_client,
        )
    else:
        gigachat_payload = await state.request_transformer.prepare_chat_completion(
            dict(openai_payload),
            giga_client,
        )
    return {
        "source": "normalized",
        "target": "gigachat",
        "openai_payload": openai_payload,
        "gigachat_payload": _serialize(gigachat_payload),
    }


@router.post("/gigachat-to-openai")
@exceptions_handler
async def gigachat_to_openai(request: Request):
    """Translate a GigaChat chat response shape to OpenAI Chat Completions form."""
    payload = await _read_json_object(request)
    source = payload.get("response", payload)
    if not isinstance(source, Mapping):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a GigaChat response object",
        )
    requested_model = str(
        payload.get("requested_model") or source.get("model") or "GigaChat"
    )
    normalized = gigachat_response_to_normalized(
        _ModelDumpWrapper(dict(source)),
        request=NormalizedChatRequest(model=requested_model),
        context=None,
    )
    openai_payload = normalized_chat_response_to_openai(
        normalized,
        requested_model=requested_model,
        context=None,
    )
    return {
        "source": "gigachat",
        "target": "openai",
        "normalized": normalized.to_json_dict(),
        "openai": openai_payload,
    }


async def _read_json_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        )
    return payload


def _extract_admin_key(request: Request) -> str | None:
    header_key = request.headers.get("x-admin-api-key")
    if header_key:
        return header_key.strip() or None

    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    authorization = authorization.strip()
    if authorization[:7].lower() == "bearer ":
        return authorization[7:].strip() or None
    return None


def _serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, Mapping):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class _ModelDumpWrapper:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self) -> dict[str, Any]:
        return self._data
