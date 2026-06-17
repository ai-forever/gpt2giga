"""Protected debug translation endpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status

from gpt2giga.api.admin.access import verify_admin_key
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.openapi_tags import OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)
from gpt2giga.protocols.gemini import (
    GeminiProtocolAdapter,
    normalized_chat_response_to_gemini,
)
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedMessage,
    NormalizedTool,
    NormalizedToolCall,
)
from gpt2giga.protocols.openai import normalized_chat_response_to_openai
from gpt2giga.providers.gigachat.adapter import (
    gigachat_response_to_normalized,
    normalized_chat_to_openai_payload,
)


SUPPORTED_TRANSLATE_FORMATS = frozenset(
    {"anthropic", "gemini", "gigachat", "normalized", "openai"}
)


router = APIRouter(
    prefix="/_debug/translate",
    tags=[OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION],
    dependencies=[Depends(verify_admin_key)],
)


@router.post("")
@exceptions_handler
async def translate(request: Request):
    """Translate a debug payload between supported protocol formats."""
    envelope = await _read_json_object(request)
    source = _read_format(envelope, "from")
    target = _read_format(envelope, "to")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected payload to be an object",
        )

    translated = await _translate_payload(
        request,
        source=source,
        target=target,
        payload=payload,
        requested_model=envelope.get("requested_model"),
    )
    response = {
        "from": source,
        "to": target,
        "payload": translated["payload"],
    }
    intermediate = translated.get("intermediate")
    if intermediate:
        response["intermediate"] = intermediate
    return response


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


@router.post("/gemini-to-normalized")
@exceptions_handler
async def gemini_to_normalized(request: Request):
    """Translate a Gemini GenerateContent request to normalized form."""
    payload = await _read_json_object(request)
    normalized = await _gemini_payload_to_normalized(request, payload)
    return {
        "source": "gemini",
        "target": "normalized",
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
        gigachat_payload = await state.request_transformer.prepare_chat_completion(
            dict(openai_payload),
            giga_client,
        )
    else:
        gigachat_payload = await state.request_transformer.prepare_chat(
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


async def _translate_payload(
    request: Request,
    *,
    source: str,
    target: str,
    payload: dict[str, Any],
    requested_model: Any = None,
) -> dict[str, Any]:
    if source == target:
        return {"payload": payload}

    if source == "openai":
        normalized = await _openai_payload_to_normalized(request, payload)
        return await _translate_normalized_request_to_target(
            request,
            normalized=normalized,
            target=target,
            intermediate={},
        )

    if source == "anthropic":
        openai_payload = _anthropic_payload_to_openai(request, payload)
        if target == "openai":
            return {"payload": openai_payload}
        normalized = await _openai_payload_to_normalized(request, openai_payload)
        return await _translate_normalized_request_to_target(
            request,
            normalized=normalized,
            target=target,
            intermediate={"openai": openai_payload},
        )

    if source == "gemini":
        normalized = await _gemini_payload_to_normalized(
            request,
            payload,
            requested_model=requested_model,
        )
        return await _translate_normalized_request_to_target(
            request,
            normalized=normalized,
            target=target,
            intermediate={},
        )

    if source == "normalized":
        normalized = NormalizedChatRequest.model_validate(
            payload.get("normalized", payload)
        )
        return await _translate_normalized_request_to_target(
            request,
            normalized=normalized,
            target=target,
            intermediate={},
        )

    if source == "gigachat":
        return _translate_gigachat_response_to_target(
            payload,
            target=target,
            requested_model=requested_model,
        )

    return _raise_unsupported_pair(source, target)


async def _translate_normalized_request_to_target(
    request: Request,
    *,
    normalized: NormalizedChatRequest,
    target: str,
    intermediate: dict[str, Any],
) -> dict[str, Any]:
    if target == "normalized":
        return {
            "payload": normalized.to_json_dict(),
            "intermediate": intermediate,
        }
    if target == "openai":
        return {
            "payload": normalized_chat_to_openai_payload(normalized),
            "intermediate": {"normalized": normalized.to_json_dict(), **intermediate},
        }
    if target == "anthropic":
        return {
            "payload": _normalized_chat_to_anthropic_payload(normalized),
            "intermediate": {"normalized": normalized.to_json_dict(), **intermediate},
        }
    if target == "gemini":
        return {
            "payload": _normalized_chat_to_gemini_payload(normalized),
            "intermediate": {"normalized": normalized.to_json_dict(), **intermediate},
        }
    if target == "gigachat":
        gigachat_payload = await _normalized_chat_to_gigachat_payload(
            request,
            normalized,
        )
        return {
            "payload": gigachat_payload["gigachat_payload"],
            "intermediate": {
                "normalized": normalized.to_json_dict(),
                "openai": gigachat_payload["openai_payload"],
                **intermediate,
            },
        }
    return _raise_unsupported_pair("normalized", target)


def _translate_gigachat_response_to_target(
    payload: dict[str, Any],
    *,
    target: str,
    requested_model: Any = None,
) -> dict[str, Any]:
    source = payload.get("response", payload)
    if not isinstance(source, Mapping):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a GigaChat response object",
        )
    model = str(requested_model or payload.get("requested_model") or "GigaChat")
    if isinstance(source, Mapping):
        model = str(
            requested_model
            or payload.get("requested_model")
            or source.get("model")
            or model
        )
    normalized = gigachat_response_to_normalized(
        _ModelDumpWrapper(dict(source)),
        request=NormalizedChatRequest(model=model),
        context=None,
    )
    if target == "normalized":
        return {"payload": normalized.to_json_dict()}
    if target == "openai":
        openai_payload = normalized_chat_response_to_openai(
            normalized,
            requested_model=model,
            context=None,
        )
        return {
            "payload": openai_payload,
            "intermediate": {"normalized": normalized.to_json_dict()},
        }
    if target == "gemini":
        gemini_payload = normalized_chat_response_to_gemini(
            normalized,
            requested_model=model,
            context=None,
        )
        return {
            "payload": gemini_payload,
            "intermediate": {"normalized": normalized.to_json_dict()},
        }
    return _raise_unsupported_pair("gigachat", target)


async def _openai_payload_to_normalized(
    request: Request,
    payload: dict[str, Any],
) -> NormalizedChatRequest:
    return await request.app.state.openai_protocol_adapter.to_normalized(
        payload,
        context=None,
    )


def _anthropic_payload_to_openai(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, Any]:
    logger = getattr(request.app.state, "logger", None)
    return _build_openai_data_from_anthropic_request(payload, logger)


async def _gemini_payload_to_normalized(
    request: Request,
    payload: dict[str, Any],
    *,
    requested_model: Any = None,
) -> NormalizedChatRequest:
    model = _debug_requested_model(requested_model, payload)
    gemini_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"model", "requested_model"}
    }
    adapter = _gemini_protocol_adapter(request)
    return adapter.generate_content_to_normalized(
        gemini_payload,
        model=model,
        context=None,
    )


def _gemini_protocol_adapter(request: Request) -> GeminiProtocolAdapter:
    adapter = getattr(request.app.state, "gemini_protocol_adapter", None)
    if adapter is None:
        adapter = GeminiProtocolAdapter()
        request.app.state.gemini_protocol_adapter = adapter
    return adapter


def _debug_requested_model(requested_model: Any, payload: dict[str, Any]) -> str:
    model = requested_model or payload.get("requested_model") or payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return "GigaChat"
    return model.strip().removeprefix("models/")


def _normalized_chat_to_gemini_payload(
    request: NormalizedChatRequest,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"contents": []}
    system_parts: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "system":
            system_parts.extend(_normalized_content_to_gemini_parts(message.content))
            continue
        parts = _normalized_message_to_gemini_parts(message)
        if parts:
            payload["contents"].append(
                {
                    "role": _normalized_role_to_gemini(message.role),
                    "parts": parts,
                }
            )

    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    if request.tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    _normalized_tool_to_gemini(tool) for tool in request.tools
                ]
            }
        ]
    tool_config = _normalized_tool_choice_to_gemini(request.tool_choice)
    if tool_config:
        payload["toolConfig"] = {"functionCallingConfig": tool_config}

    generation_config = _normalized_generation_config_to_gemini(request)
    if generation_config:
        payload["generationConfig"] = generation_config

    for key in ("cachedContent", "safetySettings", "serviceTier", "store"):
        value = request.raw_extensions.get(key)
        if value is not None:
            payload[key] = value
    return payload


def _normalized_message_to_gemini_parts(
    message: NormalizedMessage,
) -> list[dict[str, Any]]:
    if message.role == "tool" and (message.name or message.tool_call_id):
        response = {
            "name": message.name or message.tool_call_id or "",
            "response": _normalized_tool_response_content(message.content),
        }
        if message.tool_call_id:
            response["id"] = message.tool_call_id
        return [{"functionResponse": response}]

    parts = _normalized_content_to_gemini_parts(message.content)
    parts.extend(_normalized_tool_call_to_gemini(tool) for tool in message.tool_calls)
    return parts


def _normalized_content_to_gemini_parts(
    content: str | list[NormalizedContentPart] | None,
) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"text": content}]

    parts: list[dict[str, Any]] = []
    for part in content:
        if part.type == "text":
            parts.append({"text": part.text or ""})
            continue
        if part.type == "image_url":
            inline_data = _normalized_image_part_to_gemini(part)
            if inline_data:
                parts.append({"inlineData": inline_data})
            continue
        if part.type == "file":
            file_data = part.raw_extensions.get("gemini_file_data")
            if isinstance(file_data, Mapping):
                parts.append({"fileData": dict(file_data)})
    return parts


def _normalized_image_part_to_gemini(
    part: NormalizedContentPart,
) -> dict[str, str] | None:
    url = part.data.get("url") if isinstance(part.data, Mapping) else part.data
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    header, separator, data = url.partition(",")
    if separator != ",":
        return None
    mime_type = header.removeprefix("data:").split(";", maxsplit=1)[0]
    if not mime_type:
        mime_type = part.mime_type or "application/octet-stream"
    return {"mimeType": mime_type, "data": data}


def _normalized_tool_call_to_gemini(
    tool_call: NormalizedToolCall,
) -> dict[str, Any]:
    return {
        "functionCall": _compact_dict(
            {
                "id": tool_call.id,
                "name": tool_call.name or "",
                "args": _tool_arguments_to_mapping(tool_call.arguments),
            }
        )
    }


def _normalized_tool_response_content(
    content: str | list[NormalizedContentPart] | None,
) -> dict[str, Any]:
    text = _normalized_content_text(content)
    if not text:
        return {}
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return {"content": text}
    return dict(decoded) if isinstance(decoded, Mapping) else {"content": decoded}


def _normalized_tool_to_gemini(tool: NormalizedTool) -> dict[str, Any]:
    return _compact_dict(
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        }
    )


def _normalized_tool_choice_to_gemini(tool_choice: Any) -> dict[str, Any] | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        mode = {"auto": "AUTO", "none": "NONE", "required": "ANY", "any": "ANY"}.get(
            tool_choice
        )
        return {"mode": mode} if mode else None
    if not isinstance(tool_choice, Mapping):
        return None
    function = tool_choice.get("function")
    name = None
    if isinstance(function, Mapping):
        name = function.get("name")
    name = name or tool_choice.get("name")
    return {"mode": "ANY", "allowedFunctionNames": [str(name)]} if name else None


def _normalized_generation_config_to_gemini(
    request: NormalizedChatRequest,
) -> dict[str, Any]:
    generation = request.generation_config
    payload = _compact_dict(
        {
            "temperature": generation.temperature,
            "topP": generation.top_p,
            "maxOutputTokens": generation.max_tokens,
            "presencePenalty": generation.presence_penalty,
            "frequencyPenalty": generation.frequency_penalty,
            "stopSequences": generation.stop,
            "seed": generation.seed,
        }
    )
    if request.response_format is not None:
        mime_type = request.response_format.raw_extensions.get(
            "responseMimeType",
            "application/json",
        )
        payload["responseMimeType"] = mime_type
        if request.response_format.json_schema:
            payload["responseJsonSchema"] = request.response_format.json_schema
    payload.update(request.generation_config.raw_extensions)
    return payload


def _normalized_role_to_gemini(role: str) -> str:
    if role == "assistant":
        return "model"
    if role == "tool":
        return "function"
    return "user"


async def _normalized_chat_to_gigachat_payload(
    request: Request,
    normalized: NormalizedChatRequest,
) -> dict[str, Any]:
    openai_payload = normalized_chat_to_openai_payload(normalized)
    state = request.app.state
    mode = getattr(state.config.proxy_settings, "gigachat_api_mode", "v1")
    giga_client = getattr(state, "gigachat_client", None)
    if mode == "v2":
        gigachat_payload = await state.request_transformer.prepare_chat_completion(
            dict(openai_payload),
            giga_client,
        )
    else:
        gigachat_payload = await state.request_transformer.prepare_chat(
            dict(openai_payload),
            giga_client,
        )
    return {
        "openai_payload": openai_payload,
        "gigachat_payload": _serialize(gigachat_payload),
    }


def _normalized_chat_to_anthropic_payload(
    request: NormalizedChatRequest,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [],
    }
    system_blocks: list[str] = []
    for message in request.messages:
        if message.role == "system":
            text = _normalized_content_text(message.content)
            if text:
                system_blocks.append(text)
            continue
        payload["messages"].append(_message_to_anthropic(message))

    if system_blocks:
        payload["system"] = "\n".join(system_blocks)
    if request.tools:
        payload["tools"] = [_tool_to_anthropic(tool) for tool in request.tools]
    if request.tool_choice is not None:
        tool_choice = _tool_choice_to_anthropic(request.tool_choice)
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

    generation = request.generation_config
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("max_tokens", "max_tokens"),
        ("stop", "stop_sequences"),
    ):
        value = getattr(generation, source)
        if value is not None:
            payload[target] = value

    return {key: value for key, value in payload.items() if value is not None}


def _message_to_anthropic(message: NormalizedMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": _normalized_content_text(message.content),
                }
            ],
        }

    role = "assistant" if message.role == "assistant" else "user"
    content = _normalized_content_to_anthropic_blocks(message.content)
    if message.tool_calls:
        content.extend(
            _tool_call_to_anthropic(tool_call) for tool_call in message.tool_calls
        )
    return {"role": role, "content": content}


def _normalized_content_to_anthropic_blocks(
    content: str | list[NormalizedContentPart] | None,
) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    blocks: list[dict[str, Any]] = []
    for part in content:
        if part.type == "text":
            blocks.append({"type": "text", "text": part.text or ""})
        elif part.type == "image_url":
            block = _image_part_to_anthropic(part)
            if block is not None:
                blocks.append(block)
    return blocks


def _normalized_content_text(
    content: str | list[NormalizedContentPart] | None,
) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = [
        part.text or ""
        for part in content
        if isinstance(part, NormalizedContentPart) and part.type == "text"
    ]
    return "\n".join(part for part in parts if part)


def _image_part_to_anthropic(
    part: NormalizedContentPart,
) -> dict[str, Any] | None:
    data = part.data
    url = None
    if isinstance(data, Mapping):
        url = data.get("url")
    elif isinstance(data, str):
        url = data

    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:") and ";base64," in url:
        prefix, encoded = url.split(";base64,", 1)
        media_type = prefix.removeprefix("data:") or part.mime_type or "image/png"
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded,
            },
        }
    return {
        "type": "image",
        "source": {"type": "url", "url": url},
    }


def _tool_to_anthropic(tool: NormalizedTool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": tool.name,
        "input_schema": tool.parameters or {"type": "object", "properties": {}},
    }
    if tool.description:
        payload["description"] = tool.description
    return payload


def _tool_call_to_anthropic(tool_call: NormalizedToolCall) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": tool_call.id or "",
        "name": tool_call.name or "",
        "input": _tool_arguments_to_mapping(tool_call.arguments),
    }


def _tool_arguments_to_mapping(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, Mapping):
        return dict(arguments)
    if isinstance(arguments, str):
        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError:
            return {"arguments": arguments}
        if isinstance(decoded, Mapping):
            return dict(decoded)
        return {"arguments": decoded}
    if arguments is None:
        return {}
    return {"arguments": arguments}


def _tool_choice_to_anthropic(tool_choice: Any) -> dict[str, Any] | None:
    if isinstance(tool_choice, str):
        if tool_choice in {"auto", "none"}:
            return {"type": tool_choice}
        if tool_choice in {"any", "required"}:
            return {"type": "any"}
        return None
    if not isinstance(tool_choice, Mapping):
        return None
    function = tool_choice.get("function")
    if isinstance(function, Mapping) and function.get("name"):
        return {"type": "tool", "name": str(function["name"])}
    if tool_choice.get("name"):
        return {"type": "tool", "name": str(tool_choice["name"])}
    return None


def _read_format(envelope: dict[str, Any], field_name: str) -> str:
    value = envelope.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected {field_name} to be one of: "
            f"{', '.join(sorted(SUPPORTED_TRANSLATE_FORMATS))}",
        )
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_TRANSLATE_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported {field_name} format: {value}",
        )
    return normalized


def _raise_unsupported_pair(source: str, target: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported translation pair: {source} -> {target}",
    )


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


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


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
