"""Provider-to-provider request translation endpoint."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from gpt2giga.api.anthropic.request_adapter import (
    serialize_normalized_chat_request as serialize_anthropic_chat_request,
)
from gpt2giga.api.gemini.request_adapter import (
    serialize_normalized_chat_request as serialize_gemini_chat_request,
)
from gpt2giga.api.tags import TAG_TRANSLATIONS
from gpt2giga.app.dependencies import (
    get_logger_from_state,
    get_request_transformer_from_state,
)
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.json_body import read_request_json
from gpt2giga.core.contracts import NormalizedChatRequest
from gpt2giga.providers.anthropic import anthropic_provider_adapters
from gpt2giga.providers.gemini import gemini_provider_adapters
from gpt2giga.providers.openai import openai_provider_adapters

TranslationSource = Literal["openai", "anthropic", "gemini"]
TranslationTarget = Literal["openai", "anthropic", "gemini", "gigachat"]
TranslationKind = Literal["chat"]

router = APIRouter(tags=[TAG_TRANSLATIONS])


class TranslationRequest(BaseModel):
    """Provider-to-provider translation request."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "from": "openai",
                    "to": "gemini",
                    "kind": "chat",
                    "payload": {
                        "model": "gpt-4.1-mini",
                        "messages": [
                            {
                                "role": "system",
                                "content": "Answer briefly.",
                            },
                            {
                                "role": "user",
                                "content": "Write a haiku about APIs.",
                            },
                        ],
                        "temperature": 0.2,
                    },
                }
            ]
        },
    )

    source: TranslationSource = Field(alias="from")
    target: TranslationTarget = Field(alias="to")
    kind: TranslationKind = "chat"
    payload: dict[str, Any]


class TranslationResponse(BaseModel):
    """Provider-to-provider translation response."""

    model_config = ConfigDict(populate_by_name=True)

    source: TranslationSource = Field(alias="from")
    target: TranslationTarget = Field(alias="to")
    kind: TranslationKind
    endpoint: str | None = None
    payload: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


@router.post("/translate")
@exceptions_handler
async def translate_payload(request: Request):
    """Translate a provider request payload into another provider format."""
    body = await read_request_json(request)
    translation = TranslationRequest.model_validate(body)
    normalized_request = _build_normalized_chat_request(
        translation.source,
        translation.payload,
        logger=get_logger_from_state(request.app.state),
    )
    translated_payload, warnings = await _serialize_chat_request(
        normalized_request,
        target=translation.target,
        request=request,
    )
    response = TranslationResponse(
        **{
            "from": translation.source,
            "to": translation.target,
            "kind": translation.kind,
            "endpoint": _resolve_target_endpoint(
                translation.target,
                normalized_request,
            ),
            "payload": translated_payload,
            "warnings": warnings,
        }
    )
    return response.model_dump(by_alias=True, exclude_none=True)


def _build_normalized_chat_request(
    source: TranslationSource,
    payload: dict[str, Any],
    *,
    logger: Any = None,
) -> NormalizedChatRequest:
    if source == "openai":
        return openai_provider_adapters.chat.build_normalized_request(
            payload,
            logger=logger,
        )
    if source == "anthropic":
        return anthropic_provider_adapters.chat.build_normalized_request(
            payload,
            logger=logger,
        )
    return gemini_provider_adapters.chat.build_normalized_request(
        payload,
        logger=logger,
    )


async def _serialize_chat_request(
    request_data: NormalizedChatRequest,
    *,
    target: TranslationTarget,
    request: Request,
) -> tuple[dict[str, Any], list[str]]:
    if target == "openai":
        return request_data.to_backend_payload(), []
    if target == "anthropic":
        return serialize_anthropic_chat_request(request_data)
    if target == "gemini":
        return serialize_gemini_chat_request(request_data)

    if _contains_non_text_content(request_data):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": (
                        "Translation to `gigachat` supports only text/tool chat payloads. "
                        "Image and file parts require attachment upload and are not "
                        "available in this offline translation endpoint."
                    ),
                    "type": "invalid_request_error",
                    "param": "payload",
                    "code": "unsupported_translation_content",
                }
            },
        )

    transformer = get_request_transformer_from_state(request.app.state)
    payload = await transformer.prepare_chat_completion(
        request_data.to_backend_payload()
    )
    return payload, []


def _contains_non_text_content(request_data: NormalizedChatRequest) -> bool:
    for message in request_data.messages:
        if not isinstance(message.content, list):
            continue
        for part in message.content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "text":
                return True
    return False


def _resolve_target_endpoint(
    target: TranslationTarget,
    request_data: NormalizedChatRequest,
) -> str | None:
    if target == "openai":
        return "/v1/chat/completions"
    if target == "anthropic":
        return "/v1/messages"
    if target == "gemini":
        suffix = "streamGenerateContent" if request_data.stream else "generateContent"
        return f"/v1beta/models/{request_data.model}:{suffix}"
    return None
